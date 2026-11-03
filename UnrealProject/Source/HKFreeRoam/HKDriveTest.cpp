#include "HKDriveTest.h"

#include "HKCar.h"
#include "HKChaseCamera.h"
#include "HKFreeRoam.h"

#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformMisc.h"
#include "Misc/DateTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

namespace
{
	// Pad, in metres of the pad frame (X along +world X, Y along +world Y), 2 km up.
	constexpr float PadZCm = 200000.f;
	constexpr float PadMinXM = -100.f;
	constexpr float PadMaxXM = 5900.f;
	constexpr float PadHalfWidthM = 400.f;
	constexpr float SettleSeconds = 1.f;
	constexpr float LaneAccel = 0.f;
	constexpr float LaneTop = 100.f;
	constexpr float LaneLateral = -300.f;
	constexpr float LaneDrift = -100.f;
	constexpr float LaneRough = 250.f;
	constexpr float RoughStartM = 150.f;
	constexpr float RoughEndM = 270.f;

	const TCHAR* PhaseName(int32 Phase)
	{
		static const TCHAR* Names[] = {TEXT("wait"), TEXT("accel"), TEXT("brake"), TEXT("top"), TEXT("LatG60"), TEXT("LatG120"),
			TEXT("slalom"), TEXT("drift"), TEXT("handsoff"), TEXT("rough"), TEXT("done")};
		return Names[FMath::Clamp(Phase, 0, 10)];
	}

	hkdrive::Input MakeInput(float Throttle, float Brake, float Steer, bool bHandbrake)
	{
		hkdrive::Input In;
		In.Throttle = Throttle;
		In.Brake = Brake;
		In.Steer = FMath::Clamp(Steer, -1.f, 1.f);
		In.bHandbrake = bHandbrake;
		return In;
	}

	TWeakObjectPtr<AHKDriveTestRunner> ActiveRunner;
}

AHKDriveTestRunner::AHKDriveTestRunner()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PrePhysics;
}

void AHKDriveTestRunner::Start(UWorld* World, const TArray<EHKCarClass>& Classes, bool bQuitWhenDone)
{
	if (!World || Classes.Num() == 0)
	{
		return;
	}
	if (ActiveRunner.IsValid())
	{
		UE_LOG(LogHK, Warning, TEXT("HKDriveTest is already running"));
		return;
	}
	FVector Anchor = FVector::ZeroVector;
	bool bFound = false;
	for (TActorIterator<AHKCar> It(World); It; ++It)
	{
		if (It->CarId() == FName(TEXT("TuenMun_0")))
		{
			Anchor = It->GetActorLocation();
			bFound = true;
			break;
		}
	}
	if (!bFound)
	{
		if (APlayerController* PC = World->GetFirstPlayerController(); PC && PC->GetPawn())
		{
			Anchor = PC->GetPawn()->GetActorLocation();
		}
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AHKDriveTestRunner* Runner = World->SpawnActor<AHKDriveTestRunner>(AHKDriveTestRunner::StaticClass(), FTransform::Identity, Params);
	if (!Runner)
	{
		return;
	}
	ActiveRunner = Runner;
	Runner->Queue = Classes;
	Runner->bQuit = bQuitWhenDone;
	Runner->Origin = FVector(Anchor.X, Anchor.Y, PadZCm);
	Runner->Stamp = FDateTime::Now().ToString(TEXT("%Y%m%d_%H%M%S"));
	Runner->Summary = TEXT("class,metric,value,min,max,result\n");
	if (APlayerController* PC = World->GetFirstPlayerController())
	{
		Runner->PreviousView = PC->GetViewTarget();
	}
	Runner->BuildPad();
	UE_LOG(LogHK, Display, TEXT("HKDriveTest start: %d classes, pad at %s"), Classes.Num(), *Runner->Origin.ToString());
	Runner->NextClass();
}

void AHKDriveTestRunner::EndPlay(const EEndPlayReason::Type Reason)
{
	for (AActor* Actor : PadActors)
	{
		if (IsValid(Actor))
		{
			Actor->Destroy();
		}
	}
	if (IsValid(Car))
	{
		Car->Destroy();
	}
	Super::EndPlay(Reason);
}

FVector AHKDriveTestRunner::PadPoint(float XM, float YM) const
{
	return Origin + FVector(XM * 100.f, YM * 100.f, 0.f);
}

float AHKDriveTestRunner::LocalX() const
{
	return Car ? (Car->GetActorLocation().X - Origin.X) / 100.f : 0.f;
}

float AHKDriveTestRunner::LocalY() const
{
	return Car ? (Car->GetActorLocation().Y - Origin.Y) / 100.f : 0.f;
}

void AHKDriveTestRunner::BuildPad()
{
	UWorld* World = GetWorld();
	UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (!World || !Cube)
	{
		UE_LOG(LogHK, Error, TEXT("HKDriveTest: engine cube mesh missing"));
		return;
	}
	auto Block = [&](const FVector& CentreCm, const FVector& SizeCm)
	{
		AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), FTransform(CentreCm));
		if (!Actor)
		{
			return;
		}
		UStaticMeshComponent* Mesh = Actor->GetStaticMeshComponent();
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->SetStaticMesh(Cube);
		Mesh->SetWorldScale3D(SizeCm / 100.f);
		Mesh->SetCollisionProfileName(TEXT("BlockAll"));
		PadActors.Add(Actor);
	};
	// Pad top at Origin.Z. 1 m thick.
	const float LengthM = PadMaxXM - PadMinXM;
	Block(Origin + FVector((PadMinXM + LengthM * 0.5f) * 100.f, 0.f, -50.f), FVector(LengthM * 100.f, PadHalfWidthM * 200.f, 100.f));
	// Rough lane: 6 cm bumps under alternate sides every 3 m, so the body pitches and rolls.
	int32 Index = 0;
	for (float X = RoughStartM; X <= RoughEndM; X += 3.f, ++Index)
	{
		const float Side = Index % 2 == 0 ? 0.8f : -0.8f;
		Block(PadPoint(X, LaneRough + Side) + FVector(0.f, 0.f, 3.f), FVector(30.f, 120.f, 6.f));
	}
}

void AHKDriveTestRunner::NextClass()
{
	if (IsValid(Car))
	{
		const FHKCameraJitter& J = Car->GetChaseCamera()->Jitter();
		JitterYawSq += J.YawSq;
		JitterPosSq += J.PosSq;
		JitterFrames += J.Frames;
		WriteClass();
		Car->EndTestDrive();
		Car->Destroy();
		Car = nullptr;
	}
	++ClassIndex;
	if (!Queue.IsValidIndex(ClassIndex))
	{
		Finish();
		return;
	}
	Current = Queue[ClassIndex];
	Metrics.Reset();
	Metrics.Add(TEXT("Spins"), 0.f);
	Metrics.Add(TEXT("MaxYawRateDegS"), 0.f);
	JitterYawSq = JitterPosSq = 0.0;
	JitterFrames = 0;
	Trace = TEXT("t,phase,x_m,y_m,kmh,slip_deg,yaw_dps,lat_g,long_g,vert_g,roll_deg,pitch_deg,steer_in,steer_out,throttle,brake,handbrake,rear_grip,gear,rpm,locked,offroad\n");
	Clock = 0.f;
	const FName Id(*FString::Printf(TEXT("DriveTest_%s"), HKHandling::ClassName(Current)));
	Car = AHKCar::SpawnCar(GetWorld(), Current, FTransform(FRotator::ZeroRotator, PadPoint(0.f, LaneAccel) + FVector(0, 0, 20.f)), Id, ClassIndex * 3);
	if (!Car)
	{
		UE_LOG(LogHK, Error, TEXT("HKDriveTest: could not spawn a %s car"), HKHandling::ClassName(Current));
		NextClass();
		return;
	}
	Car->BeginTestDrive();
	Car->AddTickPrerequisiteActor(this);
	if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		PC->SetViewTarget(Car);
	}
	Phase = EPhase::Wait;
	PhaseTime = 0.f;
}

void AHKDriveTestRunner::Begin(EPhase NewPhase)
{
	const EPhase OldPhase = Phase;
	Phase = NewPhase;
	PhaseTime = 0.f;
	Peak = Peak2 = 0.f;
	Entry = Recover = -1.f;
	Hold = 0.f;
	LastSlip = 0.f;
	HeadingTravel = 0.f;
	bSpun = false;
	Frames = LockedFrames = 0;
	bBrakeStarted = false;
	Window.Reset();
	SteerHist.Reset();
	YawHist.Reset();
	SpeedHist.Reset();
	bSpunUp = false;
	if (NewPhase == EPhase::Brake || NewPhase == EPhase::Done)
	{
		SettleTime = 0.f; // brake continues from the 0-100 run
		return;
	}
	float LaneY = LaneAccel;
	switch (NewPhase)
	{
	case EPhase::TopSpeed: LaneY = LaneTop; break;
	case EPhase::Lat60:
	case EPhase::Lat120: LaneY = LaneLateral; break;
	case EPhase::Drift:
	case EPhase::HandsOff: LaneY = LaneDrift; break;
	case EPhase::Rough: LaneY = LaneRough; break;
	default: break;
	}
	if (OldPhase != EPhase::Wait)
	{
		const FHKCameraJitter& J = Car->GetChaseCamera()->Jitter();
		JitterYawSq += J.YawSq;
		JitterPosSq += J.PosSq;
		JitterFrames += J.Frames;
	}
	Car->ResetMotion(PadPoint(0.f, LaneY) + FVector(0, 0, 20.f), 0.f);
	SettleTime = SettleSeconds;
	StartHeading = 0.f;
}

float AHKDriveTestRunner::HoldHeading(float LaneY) const
{
	const float Yaw = FMath::DegreesToRadians(Car->GetActorRotation().Yaw);
	const float Desired = -FMath::Atan((LocalY() - LaneY) / 20.f);
	return FMath::Clamp(1.5f * (Desired - Yaw), -0.3f, 0.3f);
}

void AHKDriveTestRunner::SpeedHold(float TargetKmh, float& OutThrottle, float& OutBrake) const
{
	const float Err = TargetKmh - Car->Telemetry().Kmh;
	OutThrottle = FMath::Clamp(0.35f + 0.12f * Err, 0.f, 1.f);
	OutBrake = FMath::Clamp(-0.08f * Err - 0.4f, 0.f, 1.f);
}

void AHKDriveTestRunner::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!IsValid(Car) || Phase == EPhase::Done)
	{
		return;
	}
	const float Dt = DeltaSeconds;
	if (Phase == EPhase::Wait)
	{
		// Let the spawned car build its Chaos vehicle and drop onto the pad.
		Car->SetAutopilot(MakeInput(0.f, 0.f, 0.f, true));
		PhaseTime += Dt;
		if (PhaseTime > 2.f)
		{
			Begin(EPhase::Accel);
		}
		return;
	}
	if (SettleTime > 0.f)
	{
		SettleTime -= Dt;
		Car->SetAutopilot(MakeInput(0.f, 0.f, 0.f, true));
		if (SettleTime <= 0.f)
		{
			// Camera jitter counts only driving frames, not the drop onto the pad.
			Car->GetChaseCamera()->ResetJitter();
		}
		return;
	}
	PhaseTime += Dt;
	Clock += Dt;
	StepPhase(Dt);
	Record(Dt);
}

void AHKDriveTestRunner::Record(float Dt)
{
	if (!IsValid(Car))
	{
		return;
	}
	const FHKCarTelemetry& T = Car->Telemetry();
	float& MaxYaw = Metrics.FindOrAdd(TEXT("MaxYawRateDegS"));
	MaxYaw = FMath::Max(MaxYaw, FMath::Abs(T.YawRateDeg));
	Trace += FString::Printf(TEXT("%.4f,%s,%.2f,%.2f,%.2f,%.2f,%.2f,%.3f,%.3f,%.3f,%.2f,%.2f,%.3f,%.3f,%.3f,%.3f,%.0f,%.3f,%d,%.0f,%d,%d\n"),
		Clock, PhaseName(static_cast<int32>(Phase)), LocalX(), LocalY(), T.Kmh, T.SlipDeg, T.YawRateDeg, T.LatG, T.LongG, T.VertG,
		T.RollDeg, T.PitchDeg, CurrentSteer, T.Assist.Steer, T.Assist.Throttle, T.Assist.Brake, T.Assist.Handbrake, T.Assist.RearGrip,
		T.Gear, T.Rpm, T.LockedWheels, T.bOffroad ? 1 : 0);
}

void AHKDriveTestRunner::StepPhase(float Dt)
{
	const FHKCarTelemetry& T = Car->Telemetry();
	const float Kmh = T.Kmh;
	float Throttle = 0.f, Brake = 0.f, Steer = 0.f;
	bool bHandbrake = false;

	auto SpinUp = [&](float TargetKmh, float LaneY) -> bool
	{
		if (bSpunUp)
		{
			return true;
		}
		Car->SetAutopilot(MakeInput(1.f, 0.f, HoldHeading(LaneY), false));
		CurrentSteer = HoldHeading(LaneY);
		if (Kmh >= TargetKmh || PhaseTime > 40.f)
		{
			bSpunUp = true;
			PhaseTime = 0.f;
			PrevYaw = Car->GetActorRotation().Yaw;
		}
		return false;
	};

	switch (Phase)
	{
	case EPhase::Accel:
		Throttle = 1.f;
		Steer = HoldHeading(LaneAccel);
		Peak = FMath::Max(Peak, T.PitchDeg);
		if (Kmh >= 100.f || PhaseTime > 30.f)
		{
			Metrics.Add(TEXT("Accel0To100S"), Kmh >= 100.f ? PhaseTime : 99.f);
			Metrics.Add(TEXT("AccelSquatDeg"), Peak);
			Begin(EPhase::Brake);
			return;
		}
		break;
	case EPhase::Brake:
		Brake = 1.f;
		Steer = HoldHeading(LaneAccel);
		if (!bBrakeStarted && (T.Assist.Brake >= 0.99f || PhaseTime > 0.25f))
		{
			bBrakeStarted = true;
			BrakeStart = Car->GetActorLocation();
		}
		++Frames;
		LockedFrames += T.LockedWheels > 0 ? 1 : 0;
		Peak2 = FMath::Min(Peak2, T.PitchDeg);
		if (Kmh < 0.5f || PhaseTime > 20.f)
		{
			Metrics.Add(TEXT("Brake100To0M"), bBrakeStarted ? FVector::Dist2D(Car->GetActorLocation(), BrakeStart) / 100.f : 0.f);
			Metrics.Add(TEXT("BrakeLockPct"), 100.f * LockedFrames / FMath::Max(Frames, 1));
			Metrics.Add(TEXT("BrakeDiveDeg"), -Peak2);
			Begin(EPhase::TopSpeed);
			return;
		}
		break;
	case EPhase::TopSpeed:
		Throttle = 1.f;
		Steer = HoldHeading(LaneTop);
		SpeedHist.Add(Kmh);
		Peak = FMath::Max(Peak, Kmh);
		{
			const bool bPlateau = SpeedHist.Num() > 180 && Kmh > 60.f && SpeedHist.Last() - SpeedHist[SpeedHist.Num() - 181] < 1.f;
			const bool bEnd = LocalX() > PadMaxXM - 200.f;
			if (bPlateau || bEnd || PhaseTime > 120.f)
			{
				Metrics.Add(TEXT("TopSpeedKmh"), Peak);
				Metrics.Add(TEXT("TopSpeedLimited"), bPlateau ? 0.f : 1.f);
				Begin(EPhase::Lat60);
				return;
			}
		}
		break;
	case EPhase::Lat60:
	case EPhase::Lat120:
	{
		const float Target = Phase == EPhase::Lat60 ? 60.f : 120.f;
		if (!SpinUp(Target - 1.f, LaneLateral))
		{
			return;
		}
		SpeedHold(Target, Throttle, Brake);
		Steer = FMath::Min(1.f, PhaseTime / 8.f);
		Window.Add(FMath::Abs(T.LatG));
		if (Window.Num() > 60)
		{
			Window.RemoveAt(0);
		}
		Peak2 = FMath::Max(Peak2, FMath::Abs(T.RollDeg));
		if (Window.Num() == 60 && FMath::Abs(T.SlipDeg) < 12.f && FMath::Abs(Kmh - Target) < 0.08f * Target)
		{
			float Sum = 0.f;
			for (float V : Window)
			{
				Sum += V;
			}
			Peak = FMath::Max(Peak, Sum / 60.f);
		}
		if (PhaseTime > 9.f)
		{
			Metrics.Add(Phase == EPhase::Lat60 ? TEXT("LatG60") : TEXT("LatG120"), Peak);
			float& Roll = Metrics.FindOrAdd(TEXT("MaxRollDeg"));
			Roll = FMath::Max(Roll, Peak2);
			Begin(Phase == EPhase::Lat60 ? EPhase::Lat120 : EPhase::Slalom);
			return;
		}
		break;
	}
	case EPhase::Slalom:
		if (!SpinUp(79.f, LaneAccel))
		{
			return;
		}
		SpeedHold(80.f, Throttle, Brake);
		Steer = 0.5f * FMath::Sin(2.f * PI * 0.5f * PhaseTime);
		if (PhaseTime > 2.f)
		{
			SteerHist.Add(Steer);
			YawHist.Add(T.YawRateDeg);
		}
		if (PhaseTime > 6.f)
		{
			float MaxYaw = 0.f;
			for (float V : YawHist)
			{
				MaxYaw = FMath::Max(MaxYaw, FMath::Abs(V));
			}
			Metrics.Add(TEXT("SlalomYawGain"), MaxYaw / 0.5f);
			// Response lag: shift of the best steer/yaw correlation, in seconds (60 Hz frames).
			int32 BestLag = 0;
			double Best = -1e30;
			for (int32 Lag = 0; Lag < 60; ++Lag)
			{
				double C = 0.0;
				for (int32 I = 0; I + Lag < YawHist.Num() && I < SteerHist.Num(); ++I)
				{
					C += SteerHist[I] * YawHist[I + Lag];
				}
				if (C > Best)
				{
					Best = C;
					BestLag = Lag;
				}
			}
			Metrics.Add(TEXT("SlalomLagS"), BestLag * Dt);
			Begin(EPhase::Drift);
			return;
		}
		break;
	case EPhase::Drift:
	case EPhase::HandsOff:
	{
		if (!SpinUp(70.f, LaneDrift))
		{
			return;
		}
		const bool bCounter = Phase == EPhase::Drift;
		if (PhaseTime < 0.7f)
		{
			Throttle = 0.6f;
			Steer = 0.8f;
			bHandbrake = true;
		}
		else if (bCounter)
		{
			// Driver catches the slide: steer toward it, light throttle.
			Throttle = 0.3f;
			Steer = FMath::Clamp(LastSlip / 15.f, -1.f, 1.f);
		}
		const float Slip = FMath::Abs(T.SlipDeg);
		LastSlip = T.SlipDeg;
		Peak = FMath::Max(Peak, Slip);
		if (Entry < 0.f && Slip > 15.f)
		{
			Entry = PhaseTime;
		}
		const float Yaw = Car->GetActorRotation().Yaw;
		HeadingTravel += FMath::FindDeltaAngleDegrees(PrevYaw, Yaw);
		PrevYaw = Yaw;
		if (Slip > 80.f || FMath::Abs(HeadingTravel) > 200.f)
		{
			bSpun = true;
		}
		if (PhaseTime > 0.7f && Recover < 0.f)
		{
			if (Slip < 5.f && FMath::Abs(T.YawRateDeg) < 15.f)
			{
				Hold += Dt;
				if (Hold >= 0.3f)
				{
					Recover = PhaseTime - 0.7f - 0.3f;
				}
			}
			else
			{
				Hold = 0.f;
			}
		}
		if (PhaseTime > 8.f || (PhaseTime > 1.f && Kmh < 5.f))
		{
			if (bCounter)
			{
				Metrics.Add(TEXT("DriftEntryS"), Entry >= 0.f ? Entry : 99.f);
				Metrics.Add(TEXT("DriftRecoverS"), Recover >= 0.f ? Recover : 99.f);
				Metrics.Add(TEXT("DriftPeakSlipDeg"), Peak);
			}
			else
			{
				Metrics.Add(TEXT("HandsOffRecoverS"), Recover >= 0.f ? Recover : 99.f);
			}
			Metrics.FindOrAdd(TEXT("Spins")) += bSpun ? 1.f : 0.f;
			Begin(bCounter ? EPhase::HandsOff : EPhase::Rough);
			return;
		}
		break;
	}
	case EPhase::Rough:
		if (LocalX() < RoughStartM - 30.f)
		{
			// Run-up: reach 60 km/h before the bumps.
			if (Kmh < 60.f)
			{
				Throttle = 1.f;
			}
			else
			{
				SpeedHold(60.f, Throttle, Brake);
			}
		}
		else
		{
			SpeedHold(60.f, Throttle, Brake);
			Peak = FMath::Max(Peak, FMath::Abs(T.RollDeg));
			Peak2 = FMath::Max(Peak2, FMath::Abs(T.VertG));
		}
		Steer = HoldHeading(LaneRough);
		if (LocalX() > RoughEndM + 10.f || PhaseTime > 40.f)
		{
			Metrics.Add(TEXT("RoughMaxRollDeg"), Peak);
			Metrics.Add(TEXT("RoughMaxVertG"), Peak2);
			NextClass();
			return;
		}
		break;
	default:
		break;
	}
	CurrentSteer = Steer;
	Car->SetAutopilot(MakeInput(Throttle, Brake, Steer, bHandbrake));
}

void AHKDriveTestRunner::WriteClass()
{
	const TCHAR* Name = HKHandling::ClassName(Current);
	Metrics.Add(TEXT("CamJitterDeg"), JitterFrames > 0 ? static_cast<float>(FMath::Sqrt(JitterYawSq / JitterFrames)) : 0.f);
	Metrics.Add(TEXT("CamJitterPosCm"), JitterFrames > 0 ? static_cast<float>(FMath::Sqrt(JitterPosSq / JitterFrames)) : 0.f);
	const FHKHandling& H = HKHandling::Get(Current);
	TArray<FString> Keys;
	Metrics.GetKeys(Keys);
	Keys.Sort();
	for (const FString& Key : Keys)
	{
		const float Value = Metrics[Key];
		const FVector2f* Range = H.Targets.Find(Key);
		FString Result = TEXT("info");
		FString Lo, Hi;
		if (Range)
		{
			const bool bLo = FMath::IsNaN(Range->X) || Value >= Range->X;
			const bool bHi = FMath::IsNaN(Range->Y) || Value <= Range->Y;
			Result = bLo && bHi ? TEXT("PASS") : TEXT("FAIL");
			Failures += bLo && bHi ? 0 : 1;
			Lo = FMath::IsNaN(Range->X) ? FString() : FString::SanitizeFloat(Range->X);
			Hi = FMath::IsNaN(Range->Y) ? FString() : FString::SanitizeFloat(Range->Y);
		}
		Summary += FString::Printf(TEXT("%s,%s,%.3f,%s,%s,%s\n"), Name, *Key, Value, *Lo, *Hi, *Result);
		UE_LOG(LogHK, Display, TEXT("HKDriveTest %s %-18s %8.3f  [%s, %s]  %s"), Name, *Key, Value, *Lo, *Hi, *Result);
	}
	const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("HKDriveTest"));
	FFileHelper::SaveStringToFile(Trace, *FPaths::Combine(Dir, FString::Printf(TEXT("trace_%s_%s.csv"), Name, *Stamp)));
}

void AHKDriveTestRunner::Finish()
{
	Phase = EPhase::Done;
	const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("HKDriveTest"));
	const FString Path = FPaths::ConvertRelativePathToFull(FPaths::Combine(Dir, FString::Printf(TEXT("summary_%s.csv"), *Stamp)));
	FFileHelper::SaveStringToFile(Summary, *Path);
	UE_LOG(LogHK, Display, TEXT("HKDriveTest DONE failures=%d summary=%s"), Failures, *Path);
	if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		PC->SetViewTarget(PreviousView ? PreviousView.Get() : PC->GetPawn());
	}
	const bool bExit = bQuit;
	Destroy();
	if (bExit)
	{
		FPlatformMisc::RequestExit(false);
	}
}
