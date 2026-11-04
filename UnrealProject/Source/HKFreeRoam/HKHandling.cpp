#include "HKHandling.h"

#include "HKFreeRoam.h"
#include "HKWheelClasses.h"

#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

#include <limits>

namespace
{
	struct FHKHandlingData
	{
		bool bLoaded = false;
		FHKHandling Classes[HKCarClassCount];
		EHKCarClass DefaultClass = EHKCarClass::FR;
		TMap<FName, EHKCarClass> Assign;
		FHKCarLotConfig Lot;
	};

	FHKHandlingData& Data()
	{
		static FHKHandlingData Instance;
		return Instance;
	}

	TSharedPtr<FJsonObject> Merge(const TSharedPtr<FJsonObject>& Base, const TSharedPtr<FJsonObject>& Over)
	{
		TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
		if (Base.IsValid())
		{
			Out->Values = Base->Values;
		}
		if (!Over.IsValid())
		{
			return Out;
		}
		for (const auto& Pair : Over->Values)
		{
			// Builds the key through operator* so it compiles whether FJsonObject keys are FString or
			// another TCHAR string type (built and run on 5.8 with drivefix2).
			const FString Key(*Pair.Key);
			if (Key.StartsWith(TEXT("_")))
			{
				continue;
			}
			const TSharedPtr<FJsonValue> Existing = Out->TryGetField(Key);
			if (Existing.IsValid() && Existing->Type == EJson::Object && Pair.Value->Type == EJson::Object)
			{
				Out->SetObjectField(Key, Merge(Existing->AsObject(), Pair.Value->AsObject()));
			}
			else
			{
				Out->SetField(Key, Pair.Value);
			}
		}
		return Out;
	}

	TSharedPtr<FJsonObject> Section(const TSharedPtr<FJsonObject>& Root, const TCHAR* Name)
	{
		const TSharedPtr<FJsonObject>* Out = nullptr;
		return Root.IsValid() && Root->TryGetObjectField(Name, Out) ? *Out : MakeShared<FJsonObject>();
	}

	void Num(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Key, float& Value)
	{
		double V = 0.0;
		if (Obj->TryGetNumberField(Key, V))
		{
			Value = static_cast<float>(V);
		}
	}

	void Bool(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Key, bool& Value)
	{
		Obj->TryGetBoolField(Key, Value);
	}

	void Floats(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Key, TArray<float>& Value)
	{
		const TArray<TSharedPtr<FJsonValue>>* Array = nullptr;
		if (Obj->TryGetArrayField(Key, Array))
		{
			Value.Reset();
			for (const TSharedPtr<FJsonValue>& Item : *Array)
			{
				Value.Add(static_cast<float>(Item->AsNumber()));
			}
		}
	}

	void ReadClass(const TSharedPtr<FJsonObject>& Spec, FHKHandling& Out)
	{
		const TSharedPtr<FJsonObject> C = Section(Spec, TEXT("Chassis"));
		Num(C, TEXT("MassKg"), Out.Chassis.MassKg);
		Num(C, TEXT("ComX"), Out.Chassis.ComX);
		Num(C, TEXT("ComZ"), Out.Chassis.ComZ);
		const TSharedPtr<FJsonObject> Inertia = Section(C, TEXT("InertiaScale"));
		float IX = 1.f, IY = 1.f, IZ = 1.f;
		Num(Inertia, TEXT("X"), IX);
		Num(Inertia, TEXT("Y"), IY);
		Num(Inertia, TEXT("Z"), IZ);
		Out.Chassis.InertiaScale = FVector(IX, IY, IZ);
		Num(C, TEXT("DragCoefficient"), Out.Chassis.DragCoefficient);
		FString Drive;
		if (C->TryGetStringField(TEXT("Drive"), Drive))
		{
			Out.Chassis.Drive = Drive == TEXT("FWD") ? EHKDrive::FWD : (Drive == TEXT("AWD") || Drive == TEXT("4WD") ? EHKDrive::AWD : EHKDrive::RWD);
		}
		Num(C, TEXT("FrontRearSplit"), Out.Chassis.FrontRearSplit);
		Num(C, TEXT("IdleBrake"), Out.Chassis.IdleBrake);

		const TSharedPtr<FJsonObject> E = Section(Spec, TEXT("Engine"));
		FHKEngineConfig& En = Out.Engine;
		Num(E, TEXT("MaxTorqueNm"), En.MaxTorqueNm);
		Num(E, TEXT("MaxRPM"), En.MaxRPM);
		Num(E, TEXT("IdleRPM"), En.IdleRPM);
		Floats(E, TEXT("TorqueRpm"), En.TorqueRpm);
		Floats(E, TEXT("TorqueScale"), En.TorqueScale);
		Num(E, TEXT("RevUpMOI"), En.RevUpMOI);
		Num(E, TEXT("RevDownRate"), En.RevDownRate);
		Num(E, TEXT("EngineBrake"), En.EngineBrake);
		Num(E, TEXT("FinalRatio"), En.FinalRatio);
		Floats(E, TEXT("Gears"), En.Gears);
		Num(E, TEXT("ReverseGear"), En.ReverseGear);
		Num(E, TEXT("ChangeUpRPM"), En.ChangeUpRPM);
		Num(E, TEXT("ChangeDownRPM"), En.ChangeDownRPM);
		Num(E, TEXT("ShiftTime"), En.ShiftTime);

		const TSharedPtr<FJsonObject> W = Section(Spec, TEXT("Wheels"));
		FHKWheelsConfig& Wh = Out.Wheels;
		Num(W, TEXT("RadiusCm"), Wh.RadiusCm);
		Num(W, TEXT("WidthCm"), Wh.WidthCm);
		Num(W, TEXT("RideHzFront"), Wh.RideHzFront);
		Num(W, TEXT("RideHzRear"), Wh.RideHzRear);
		Num(W, TEXT("DampingRatio"), Wh.DampingRatio);
		Num(W, TEXT("Preload"), Wh.Preload);
		Num(W, TEXT("MaxRaiseCm"), Wh.MaxRaiseCm);
		Num(W, TEXT("MaxDropCm"), Wh.MaxDropCm);
		Num(W, TEXT("FrictionFront"), Wh.FrictionFront);
		Num(W, TEXT("FrictionRear"), Wh.FrictionRear);
		Num(W, TEXT("CorneringStiffness"), Wh.CorneringStiffness);
		Num(W, TEXT("WheelLoadRatio"), Wh.WheelLoadRatio);
		Num(W, TEXT("BrakeTorqueFront"), Wh.BrakeTorqueFront);
		Num(W, TEXT("BrakeTorqueRear"), Wh.BrakeTorqueRear);
		Num(W, TEXT("HandbrakeTorque"), Wh.HandbrakeTorque);
		Bool(W, TEXT("bABS"), Wh.bABS);
		Bool(W, TEXT("bTractionControlFront"), Wh.bTractionControlFront);
		Bool(W, TEXT("bTractionControlRear"), Wh.bTractionControlRear);
		Num(W, TEXT("RollbarScaling"), Wh.RollbarScaling);

		const TSharedPtr<FJsonObject> A = Section(Spec, TEXT("Assist"));
		int32 Count = 0;
		const hkdrive::ParamField* Fields = hkdrive::ParamFields(Count);
		for (int32 Index = 0; Index < Count; ++Index)
		{
			Num(A, UTF8_TO_TCHAR(Fields[Index].Name), Out.Assist.*(Fields[Index].Member));
		}
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : A->Values)
		{
			bool bKnown = Pair.Key.StartsWith(TEXT("_"));
			for (int32 Index = 0; Index < Count && !bKnown; ++Index)
			{
				bKnown = Pair.Key == UTF8_TO_TCHAR(Fields[Index].Name);
			}
			if (!bKnown)
			{
				UE_LOG(LogHK, Warning, TEXT("vehicles.json: unknown Assist field %s"), *Pair.Key);
			}
		}
		// VelLat is measured at the actor origin, the wheelbase centre.
		Out.Assist.RearAxleM = Out.Assist.WheelbaseM * 0.5f;

		const TSharedPtr<FJsonObject> Cam = Section(Spec, TEXT("Camera"));
		FHKCameraConfig& Ca = Out.Camera;
		Num(Cam, TEXT("ArmCm"), Ca.ArmCm);
		Num(Cam, TEXT("HeightCm"), Ca.HeightCm);
		Num(Cam, TEXT("PitchDeg"), Ca.PitchDeg);
		Num(Cam, TEXT("BaseFov"), Ca.BaseFov);
		Num(Cam, TEXT("FovAdd"), Ca.FovAdd);
		Num(Cam, TEXT("FovSpeedKmh"), Ca.FovSpeedKmh);
		Num(Cam, TEXT("AccelPullCm"), Ca.AccelPullCm);
		Num(Cam, TEXT("BrakePushCm"), Ca.BrakePushCm);
		Num(Cam, TEXT("SpeedPullCm"), Ca.SpeedPullCm);
		Num(Cam, TEXT("LatShiftCm"), Ca.LatShiftCm);
		Num(Cam, TEXT("LatRollDeg"), Ca.LatRollDeg);
		Num(Cam, TEXT("YawStiffness"), Ca.YawStiffness);
		Num(Cam, TEXT("YawStiffnessFast"), Ca.YawStiffnessFast);
		Num(Cam, TEXT("VelocityBlend"), Ca.VelocityBlend);
		Num(Cam, TEXT("ShakeStartKmh"), Ca.ShakeStartKmh);
		Num(Cam, TEXT("ShakeDeg"), Ca.ShakeDeg);
		Num(Cam, TEXT("BumpShakeDeg"), Ca.BumpShakeDeg);
		Num(Cam, TEXT("RecenterDelay"), Ca.RecenterDelay);
		Bool(Cam, TEXT("RecenterWhenParked"), Ca.bRecenterWhenParked);
		Num(Cam, TEXT("LagSpeed"), Ca.LagSpeed);

		const TSharedPtr<FJsonObject> B = Section(Spec, TEXT("Body"));
		Num(B, TEXT("CabinX"), Out.Body.CabinX);
		Num(B, TEXT("CabinLength"), Out.Body.CabinLength);
		Num(B, TEXT("CabinWidth"), Out.Body.CabinWidth);
		Num(B, TEXT("CabinHeight"), Out.Body.CabinHeight);

		Out.Targets.Reset();
		const TSharedPtr<FJsonObject> T = Section(Spec, TEXT("Targets"));
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : T->Values)
		{
			const TArray<TSharedPtr<FJsonValue>>* Range = nullptr;
			if (!Pair.Value->TryGetArray(Range) || Range->Num() != 2)
			{
				continue;
			}
			auto Bound = [](const TSharedPtr<FJsonValue>& V) { return V->IsNull() ? std::numeric_limits<float>::quiet_NaN() : static_cast<float>(V->AsNumber()); };
			Out.Targets.Add(Pair.Key, FVector2f(Bound((*Range)[0]), Bound((*Range)[1])));
		}
	}

	void Load(FHKHandlingData& D)
	{
		D = FHKHandlingData();
		D.bLoaded = true;
		for (int32 Index = 0; Index < HKCarClassCount; ++Index)
		{
			D.Classes[Index].Class = static_cast<EHKCarClass>(Index);
		}
		FString Text;
		const FString Path = HKHandling::ConfigPath();
		TSharedPtr<FJsonObject> Root;
		if (!FFileHelper::LoadFileToString(Text, *Path) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid())
		{
			UE_LOG(LogHK, Warning, TEXT("Handling config %s missing or invalid; every car uses built-in defaults"), *Path);
			return;
		}
		const TSharedPtr<FJsonObject> Defaults = Section(Root, TEXT("Defaults"));
		const TSharedPtr<FJsonObject> Classes = Section(Root, TEXT("classes"));
		for (int32 Index = 0; Index < HKCarClassCount; ++Index)
		{
			const EHKCarClass Class = static_cast<EHKCarClass>(Index);
			const TSharedPtr<FJsonObject>* Block = nullptr;
			if (!Classes->TryGetObjectField(HKHandling::ClassName(Class), Block))
			{
				UE_LOG(LogHK, Warning, TEXT("vehicles.json has no class %s; it uses Defaults"), HKHandling::ClassName(Class));
			}
			ReadClass(Merge(Defaults, Block ? *Block : nullptr), D.Classes[Index]);
		}
		FString DefaultName;
		if (Root->TryGetStringField(TEXT("default_class"), DefaultName))
		{
			HKHandling::ParseClass(DefaultName, D.DefaultClass);
		}
		const TSharedPtr<FJsonObject> Assign = Section(Root, TEXT("assign"));
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Assign->Values)
		{
			EHKCarClass Class;
			if (!Pair.Key.StartsWith(TEXT("_")) && HKHandling::ParseClass(Pair.Value->AsString(), Class))
			{
				D.Assign.Add(FName(*Pair.Key), Class);
			}
		}
		const TSharedPtr<FJsonObject> Lot = Section(Root, TEXT("lot"));
		Bool(Lot, TEXT("enabled"), D.Lot.bEnabled);
		FString Anchor;
		if (Lot->TryGetStringField(TEXT("anchor"), Anchor))
		{
			D.Lot.Anchor = FName(*Anchor);
		}
		TArray<FString> LotClasses;
		if (Lot->TryGetStringArrayField(TEXT("classes"), LotClasses))
		{
			for (const FString& Name : LotClasses)
			{
				EHKCarClass Class;
				if (HKHandling::ParseClass(Name, Class))
				{
					D.Lot.Classes.Add(Class);
				}
			}
		}
		Num(Lot, TEXT("spacing_m"), D.Lot.SpacingM);
		UE_LOG(LogHK, Display, TEXT("Handling loaded from %s: %d assigned cars, lot %s"), *Path, D.Assign.Num(), D.Lot.bEnabled ? TEXT("on") : TEXT("off"));
	}

	FHKHandlingData& Loaded()
	{
		FHKHandlingData& D = Data();
		if (!D.bLoaded)
		{
			Load(D);
			for (int32 Index = 0; Index < HKCarClassCount; ++Index)
			{
				HKHandling::WriteWheelDefaults(static_cast<EHKCarClass>(Index));
			}
		}
		return D;
	}
}

FString HKHandling::ConfigPath()
{
	return FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT("../data/config/vehicles.json")));
}

const FHKHandling& HKHandling::Get(EHKCarClass Class)
{
	return Loaded().Classes[FMath::Clamp(static_cast<int32>(Class), 0, HKCarClassCount - 1)];
}

EHKCarClass HKHandling::ClassForCar(FName CarId)
{
	const FHKHandlingData& D = Loaded();
	if (const EHKCarClass* Found = D.Assign.Find(CarId))
	{
		return *Found;
	}
	if (CarId.IsNone())
	{
		return D.DefaultClass;
	}
	// Unlisted cars: stable spread over the classes.
	return static_cast<EHKCarClass>(GetTypeHash(CarId.ToString()) % HKCarClassCount);
}

const FHKCarLotConfig& HKHandling::Lot()
{
	return Loaded().Lot;
}

bool HKHandling::Reload()
{
	Data().bLoaded = false;
	Loaded();
	return true;
}

const TCHAR* HKHandling::ClassName(EHKCarClass Class)
{
	switch (Class)
	{
	case EHKCarClass::FF:
		return TEXT("FF");
	case EHKCarClass::AWD:
		return TEXT("AWD");
	default:
		return TEXT("FR");
	}
}

bool HKHandling::ParseClass(const FString& Text, EHKCarClass& Out)
{
	const FString Upper = Text.ToUpper();
	if (Upper == TEXT("FR") || Upper == TEXT("RWD"))
	{
		Out = EHKCarClass::FR;
		return true;
	}
	if (Upper == TEXT("FF") || Upper == TEXT("FWD"))
	{
		Out = EHKCarClass::FF;
		return true;
	}
	if (Upper == TEXT("AWD") || Upper == TEXT("4WD"))
	{
		Out = EHKCarClass::AWD;
		return true;
	}
	return false;
}

UClass* HKHandling::WheelClass(EHKCarClass Class, bool bFront)
{
	switch (Class)
	{
	case EHKCarClass::FF:
		return bFront ? UHKWheelFront_FF::StaticClass() : UHKWheelRear_FF::StaticClass();
	case EHKCarClass::AWD:
		return bFront ? UHKWheelFront_AWD::StaticClass() : UHKWheelRear_AWD::StaticClass();
	default:
		return bFront ? UHKWheelFront_FR::StaticClass() : UHKWheelRear_FR::StaticClass();
	}
}

void HKHandling::WriteWheelDefaults(EHKCarClass Class)
{
	const FHKHandling& H = Data().Classes[static_cast<int32>(Class)];
	const FHKWheelsConfig& W = H.Wheels;
	const float FrontShare = FMath::Clamp(0.5f + H.Chassis.ComX / (H.Assist.WheelbaseM * 100.f), 0.2f, 0.8f);
	for (const bool bFront : {true, false})
	{
		UChaosVehicleWheel* Wheel = WheelClass(Class, bFront)->GetDefaultObject<UChaosVehicleWheel>();
		const float CornerKg = H.Chassis.MassKg * (bFront ? FrontShare : 1.f - FrontShare) * 0.5f;
		const float Omega = 2.f * PI * (bFront ? W.RideHzFront : W.RideHzRear);
		// Chaos scales SpringRate by 100 internally (see AGENTS.md): N/m / 100.
		Wheel->SpringRate = Omega * Omega * CornerKg / 100.f;
		Wheel->SpringPreload = W.Preload;
		Wheel->SuspensionDampingRatio = W.DampingRatio;
		// Static sag is g / omega^2; keep the raise travel above it so the car never sits on the stop.
		const float SagCm = 981.f / (Omega * Omega);
		Wheel->SuspensionMaxRaise = FMath::Max(W.MaxRaiseCm, SagCm + 4.f);
		Wheel->SuspensionMaxDrop = W.MaxDropCm;
		Wheel->WheelRadius = W.RadiusCm;
		Wheel->WheelWidth = W.WidthCm;
		Wheel->FrictionForceMultiplier = bFront ? W.FrictionFront : W.FrictionRear;
		Wheel->CorneringStiffness = W.CorneringStiffness;
		Wheel->WheelLoadRatio = W.WheelLoadRatio;
		Wheel->RollbarScaling = W.RollbarScaling;
		Wheel->MaxBrakeTorque = bFront ? W.BrakeTorqueFront : W.BrakeTorqueRear;
		Wheel->MaxHandBrakeTorque = bFront ? 0.f : W.HandbrakeTorque;
		Wheel->bAffectedByHandbrake = !bFront;
		Wheel->bAffectedBySteering = bFront;
		Wheel->MaxSteerAngle = bFront ? H.Assist.MaxSteerDeg : 0.f;
		Wheel->bABSEnabled = W.bABS;
		Wheel->bTractionControlEnabled = bFront ? W.bTractionControlFront : W.bTractionControlRear;
		// The drivetrain: only the driven axle gets engine torque.
		Wheel->bAffectedByEngine = H.Chassis.Drive == EHKDrive::AWD || (bFront ? H.Chassis.Drive == EHKDrive::FWD : H.Chassis.Drive == EHKDrive::RWD);
	}
}
