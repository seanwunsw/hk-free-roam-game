#include "HKMapLabels.h"

#include "HKFreeRoam.h"

#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	// "x y x y ..." in decimetres.
	void ParsePoints(const FString& Text, TArray<FVector2D>& Out)
	{
		Out.Reset();
		const TCHAR* Cursor = *Text;
		double Pending = 0.0;
		bool bHavePending = false;
		while (*Cursor)
		{
			while (*Cursor == TEXT(' '))
			{
				++Cursor;
			}
			if (!*Cursor)
			{
				break;
			}
			TCHAR* End = nullptr;
			const int64 Value = FCString::Strtoi64(Cursor, &End, 10);
			if (End == Cursor)
			{
				break;
			}
			Cursor = End;
			if (bHavePending)
			{
				Out.Add(FVector2D(Pending, Value * 0.1));
				bHavePending = false;
			}
			else
			{
				Pending = Value * 0.1;
				bHavePending = true;
			}
		}
	}

	void ReadPoint(const TSharedPtr<FJsonObject>& Object, FHKLabelPoint& Point)
	{
		Object->TryGetStringField(TEXT("zh"), Point.Zh);
		Object->TryGetStringField(TEXT("en"), Point.En);
		Object->TryGetStringField(TEXT("kind"), Point.Kind);
		Object->TryGetNumberField(TEXT("x_m"), Point.X);
		Object->TryGetNumberField(TEXT("y_m"), Point.Y);
		const TArray<TSharedPtr<FJsonValue>>* Rings = nullptr;
		if (Object->TryGetArrayField(TEXT("rings"), Rings) && Rings)
		{
			for (const TSharedPtr<FJsonValue>& Ring : *Rings)
			{
				ParsePoints(Ring->AsString(), Point.Rings.AddDefaulted_GetRef());
			}
		}
	}

	void ReadPoints(const TSharedPtr<FJsonObject>& Root, const TCHAR* Field, TArray<FHKLabelPoint>& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Array = nullptr;
		if (!Root->TryGetArrayField(Field, Array) || !Array)
		{
			return;
		}
		for (const TSharedPtr<FJsonValue>& Value : *Array)
		{
			const TSharedPtr<FJsonObject> Object = Value->AsObject();
			if (Object)
			{
				ReadPoint(Object, Out.AddDefaulted_GetRef());
			}
		}
	}

	double SegmentDistance(const FVector2D& P, const FVector2D& A, const FVector2D& B, FVector2D& OutClosest)
	{
		const FVector2D AB = B - A;
		const double Len2 = AB.SizeSquared();
		const double T = Len2 > 1e-6 ? FMath::Clamp(FVector2D::DotProduct(P - A, AB) / Len2, 0.0, 1.0) : 0.0;
		OutClosest = A + AB * T;
		return FVector2D::Distance(P, OutClosest);
	}

	bool InsideRing(const TArray<FVector2D>& Ring, double X, double Y)
	{
		bool bInside = false;
		for (int32 I = 0, J = Ring.Num() - 1; I < Ring.Num(); J = I++)
		{
			const FVector2D& A = Ring[I];
			const FVector2D& B = Ring[J];
			if ((A.Y > Y) != (B.Y > Y) && X < (B.X - A.X) * (Y - A.Y) / (B.Y - A.Y) + A.X)
			{
				bInside = !bInside;
			}
		}
		return bInside;
	}

	const FHKLabelPoint* Nearest(const TArray<FHKLabelPoint>& Points, double X, double Y, double MaxDistance)
	{
		const FHKLabelPoint* Best = nullptr;
		double BestD2 = MaxDistance * MaxDistance;
		for (const FHKLabelPoint& Point : Points)
		{
			const double D2 = FMath::Square(Point.X - X) + FMath::Square(Point.Y - Y);
			if (D2 < BestD2)
			{
				BestD2 = D2;
				Best = &Point;
			}
		}
		return Best;
	}
}

bool FHKMapLabels::Load(const FString& Path)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		UE_LOG(LogHK, Warning, TEXT("road_names.json was not loaded: %s"), *Path);
		return false;
	}
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		UE_LOG(LogHK, Warning, TEXT("road_names.json could not be parsed: %s"), *Path);
		return false;
	}
	Text.Empty();

	const TArray<TSharedPtr<FJsonValue>>* NameArray = nullptr;
	if (Root->TryGetArrayField(TEXT("names"), NameArray) && NameArray)
	{
		for (const TSharedPtr<FJsonValue>& Value : *NameArray)
		{
			const TArray<TSharedPtr<FJsonValue>>& Pair = Value->AsArray();
			Names.Emplace(Pair.Num() > 0 ? Pair[0]->AsString() : FString(), Pair.Num() > 1 ? Pair[1]->AsString() : FString());
		}
	}
	const TArray<TSharedPtr<FJsonValue>>* RoadArray = nullptr;
	if (Root->TryGetArrayField(TEXT("roads"), RoadArray) && RoadArray)
	{
		Roads.Reserve(RoadArray->Num());
		for (const TSharedPtr<FJsonValue>& Value : *RoadArray)
		{
			const TSharedPtr<FJsonObject> Object = Value->AsObject();
			FHKNamedRoad& Road = Roads.AddDefaulted_GetRef();
			if (!Object)
			{
				continue;
			}
			double NameIndex = -1.0;
			Object->TryGetNumberField(TEXT("n"), NameIndex);
			Road.Name = Names.IsValidIndex((int32)NameIndex) ? (int32)NameIndex : INDEX_NONE;
			Object->TryGetStringField(TEXT("c"), Road.Class);
			FString PointText;
			Object->TryGetStringField(TEXT("p"), PointText);
			ParsePoints(PointText, Road.Points);
		}
	}
	const TSharedPtr<FJsonObject>* Grid = nullptr;
	if (Root->TryGetObjectField(TEXT("grid"), Grid) && Grid && Grid->IsValid())
	{
		double Nx = 0, Ny = 0;
		(*Grid)->TryGetNumberField(TEXT("cell_m"), CellM);
		(*Grid)->TryGetNumberField(TEXT("min_x_m"), GridMinX);
		(*Grid)->TryGetNumberField(TEXT("min_y_m"), GridMinY);
		(*Grid)->TryGetNumberField(TEXT("nx"), Nx);
		(*Grid)->TryGetNumberField(TEXT("ny"), Ny);
		NX = FMath::Max(0, (int32)Nx);
		NY = FMath::Max(0, (int32)Ny);
		CellM = FMath::Max(CellM, 1.0);
		Cells.SetNum(NX * NY);
		const TSharedPtr<FJsonObject>* CellObject = nullptr;
		if ((*Grid)->TryGetObjectField(TEXT("cells"), CellObject) && CellObject && CellObject->IsValid())
		{
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : (*CellObject)->Values)
			{
				const int32 Cell = FCString::Atoi(*Entry.Key);
				if (!Cells.IsValidIndex(Cell))
				{
					continue;
				}
				for (const TSharedPtr<FJsonValue>& Index : Entry.Value->AsArray())
				{
					const int32 Road = (int32)Index->AsNumber();
					if (Roads.IsValidIndex(Road))
					{
						Cells[Cell].Add(Road);
					}
				}
			}
		}
	}
	ReadPoints(Root, TEXT("places"), Places);
	ReadPoints(Root, TEXT("districts"), Districts);
	ReadPoints(Root, TEXT("landmarks"), Landmarks);
	UE_LOG(LogHK, Display, TEXT("Road names: %d roads, %d names, %d places, %d districts, %d landmarks from %s"),
		Roads.Num(), Names.Num(), Places.Num(), Districts.Num(), Landmarks.Num(), *Path);
	return Roads.Num() > 0;
}

void FHKMapLabels::CellRange(double MinX, double MinY, double MaxX, double MaxY, int32& I0, int32& J0, int32& I1, int32& J1) const
{
	I0 = FMath::Clamp(FMath::FloorToInt32((MinX - GridMinX) / CellM), 0, FMath::Max(NX - 1, 0));
	J0 = FMath::Clamp(FMath::FloorToInt32((MinY - GridMinY) / CellM), 0, FMath::Max(NY - 1, 0));
	I1 = FMath::Clamp(FMath::FloorToInt32((MaxX - GridMinX) / CellM), 0, FMath::Max(NX - 1, 0));
	J1 = FMath::Clamp(FMath::FloorToInt32((MaxY - GridMinY) / CellM), 0, FMath::Max(NY - 1, 0));
}

bool FHKMapLabels::FindRoad(double X, double Y, double MaxDistance, const FVector2D* Heading, FHKRoadHit& OutHit) const
{
	if (NX == 0 || NY == 0)
	{
		return false;
	}
	int32 I0, J0, I1, J1;
	CellRange(X - MaxDistance, Y - MaxDistance, X + MaxDistance, Y + MaxDistance, I0, J0, I1, J1);
	const FVector2D P(X, Y);
	double BestScore = TNumericLimits<double>::Max();
	for (int32 J = J0; J <= J1; ++J)
	{
		for (int32 I = I0; I <= I1; ++I)
		{
			for (const int32 RoadIndex : Cells[J * NX + I])
			{
				const FHKNamedRoad& Road = Roads[RoadIndex];
				for (int32 K = 0; K + 1 < Road.Points.Num(); ++K)
				{
					FVector2D Closest;
					const double Distance = SegmentDistance(P, Road.Points[K], Road.Points[K + 1], Closest);
					if (Distance > MaxDistance)
					{
						continue;
					}
					double Score = Distance;
					if (Heading)
					{
						const FVector2D Along = (Road.Points[K + 1] - Road.Points[K]).GetSafeNormal();
						// Either direction of travel counts: roads are drawn once for both carriageways.
						const double Align = FMath::Abs(FVector2D::DotProduct(Along, *Heading));
						Score += (1.0 - Align) * 20.0;
					}
					if (Score < BestScore)
					{
						BestScore = Score;
						OutHit.Road = RoadIndex;
						OutHit.Distance = Distance;
						OutHit.Point = Closest;
					}
				}
			}
		}
	}
	return OutHit.Road != INDEX_NONE;
}

void FHKMapLabels::RoadsInBox(double MinX, double MinY, double MaxX, double MaxY, TArray<int32>& OutRoads) const
{
	OutRoads.Reset();
	if (NX == 0 || NY == 0)
	{
		return;
	}
	int32 I0, J0, I1, J1;
	CellRange(MinX, MinY, MaxX, MaxY, I0, J0, I1, J1);
	TSet<int32> Seen;
	for (int32 J = J0; J <= J1; ++J)
	{
		for (int32 I = I0; I <= I1; ++I)
		{
			for (const int32 RoadIndex : Cells[J * NX + I])
			{
				if (!Seen.Contains(RoadIndex))
				{
					Seen.Add(RoadIndex);
					OutRoads.Add(RoadIndex);
				}
			}
		}
	}
}

const FHKLabelPoint* FHKMapLabels::FindDistrict(double X, double Y) const
{
	for (const FHKLabelPoint& District : Districts)
	{
		for (const TArray<FVector2D>& Ring : District.Rings)
		{
			if (InsideRing(Ring, X, Y))
			{
				return &District;
			}
		}
	}
	return Nearest(Districts, X, Y, 3000.0);
}

const FHKLabelPoint* FHKMapLabels::NearestPlace(double X, double Y, double MaxDistance) const
{
	return Nearest(Places, X, Y, MaxDistance);
}

const FHKLabelPoint* FHKMapLabels::NearestLandmark(double X, double Y, double MaxDistance) const
{
	return Nearest(Landmarks, X, Y, MaxDistance);
}

const FString& FHKMapLabels::NameZh(int32 Road) const
{
	static const FString Empty;
	return Roads.IsValidIndex(Road) && Names.IsValidIndex(Roads[Road].Name) ? Names[Roads[Road].Name].Key : Empty;
}

const FString& FHKMapLabels::NameEn(int32 Road) const
{
	static const FString Empty;
	return Roads.IsValidIndex(Road) && Names.IsValidIndex(Roads[Road].Name) ? Names[Roads[Road].Name].Value : Empty;
}
