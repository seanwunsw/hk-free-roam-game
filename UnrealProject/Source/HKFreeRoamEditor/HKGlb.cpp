#include "HKGlb.h"

#include "Misc/FileHelper.h"

namespace
{
bool ChunkIs(const uint8* Type, const ANSICHAR* Name)
{
	return FMemory::Memcmp(Type, Name, 4) == 0;
}

bool ReadFloats(const TArray<uint8>& Bin, int32 ByteOffset, int32 Count, TArray<float>& Out)
{
	if (Count < 0 || ByteOffset < 0 || ByteOffset + Count * (int32)sizeof(float) > Bin.Num())
	{
		return false;
	}
	Out.SetNumUninitialized(Count);
	if (Count > 0)
	{
		FMemory::Memcpy(Out.GetData(), Bin.GetData() + ByteOffset, Count * sizeof(float));
	}
	return true;
}
}

bool HKLoadGlb(const FString& Path, TArray<FHKGlbPrim>& OutPrims, FString& OutError)
{
	OutPrims.Reset();
	TArray<uint8> File;
	if (!FFileHelper::LoadFileToArray(File, *Path) || File.Num() < 20)
	{
		OutError = TEXT("cannot read glb");
		return false;
	}
	if (FMemory::Memcmp(File.GetData(), "glTF", 4) != 0)
	{
		OutError = TEXT("not a glb");
		return false;
	}
	const uint32 Total = *reinterpret_cast<const uint32*>(File.GetData() + 8);
	const int32 Limit = FMath::Min<int32>((int32)Total, File.Num());
	TArray<uint8> Bin;
	TArray<uint8> Hkgm;
	int32 Offset = 12;
	while (Offset + 8 <= Limit)
	{
		const uint32 ChunkLen = *reinterpret_cast<const uint32*>(File.GetData() + Offset);
		const uint8* Type = File.GetData() + Offset + 4;
		Offset += 8;
		if (ChunkLen > (uint32)(Limit - Offset))
		{
			OutError = TEXT("truncated glb chunk");
			return false;
		}
		if (ChunkIs(Type, "BIN\0"))
		{
			Bin.Append(File.GetData() + Offset, ChunkLen);
		}
		else if (ChunkIs(Type, "HKGM"))
		{
			Hkgm.Append(File.GetData() + Offset, ChunkLen);
		}
		Offset += (int32)ChunkLen;
	}
	if (Hkgm.Num() < 4 || Bin.Num() == 0)
	{
		OutError = TEXT("missing HKGM or BIN chunk");
		return false;
	}
	const uint32 Count = *reinterpret_cast<const uint32*>(Hkgm.GetData());
	if (Count > 100000 || 4 + Count * 24 > (uint32)Hkgm.Num())
	{
		OutError = TEXT("bad HKGM count");
		return false;
	}
	int32 Cursor = 4;
	for (uint32 PrimIndex = 0; PrimIndex < Count; ++PrimIndex)
	{
		const uint32* Header = reinterpret_cast<const uint32*>(Hkgm.GetData() + Cursor);
		Cursor += 24;
		const uint32 VertOff = Header[0];
		const uint32 VertCount = Header[1];
		const uint32 IndexOff = Header[2];
		const uint32 IndexCount = Header[3];
		const uint32 Material = Header[5];
		if (VertCount == 0 || IndexCount < 3 || VertCount > 2000000 || IndexCount > 6000000)
		{
			continue;
		}
		TArray<float> Pos, Nrm, Uv, Col;
		TArray<uint32> Indices;
		Indices.SetNumUninitialized(IndexCount);
		if (!ReadFloats(Bin, (int32)VertOff, (int32)VertCount * 3, Pos) ||
			!ReadFloats(Bin, (int32)VertOff + (int32)VertCount * 12, (int32)VertCount * 3, Nrm) ||
			!ReadFloats(Bin, (int32)VertOff + (int32)VertCount * 24, (int32)VertCount * 2, Uv) ||
			!ReadFloats(Bin, (int32)VertOff + (int32)VertCount * 32, (int32)VertCount * 4, Col) ||
			(int32)IndexOff + (int32)IndexCount * 4 > Bin.Num())
		{
			OutError = FString::Printf(TEXT("primitive %u is out of range"), PrimIndex);
			return false;
		}
		FMemory::Memcpy(Indices.GetData(), Bin.GetData() + IndexOff, IndexCount * 4);
		FHKGlbPrim& Prim = OutPrims.AddDefaulted_GetRef();
		Prim.Material = (int32)Material;
		Prim.Indices = MoveTemp(Indices);
		Prim.Positions.SetNum(VertCount);
		Prim.Normals.SetNum(VertCount);
		Prim.UVs.SetNum(VertCount);
		Prim.Colors.SetNum(VertCount);
		for (uint32 Vertex = 0; Vertex < VertCount; ++Vertex)
		{
			Prim.Positions[Vertex] = FVector3f(Pos[Vertex * 3], Pos[Vertex * 3 + 1], Pos[Vertex * 3 + 2]);
			Prim.Normals[Vertex] = FVector3f(Nrm[Vertex * 3], Nrm[Vertex * 3 + 1], Nrm[Vertex * 3 + 2]);
			Prim.UVs[Vertex] = FVector2f(Uv[Vertex * 2], Uv[Vertex * 2 + 1]);
			Prim.Colors[Vertex] = FVector4f(Col[Vertex * 4], Col[Vertex * 4 + 1], Col[Vertex * 4 + 2], Col[Vertex * 4 + 3]);
		}
	}
	return OutPrims.Num() > 0;
}
