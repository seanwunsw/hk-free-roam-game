#pragma once

// Lookup-table evaluator for the Hong Kong coordinate warp.
// Binary layout is written by tools/hkwarp/warp.py (magic HKWARP01).
// +X is east, +Y is north, units are metres. No Unreal headers; safe for g++ and UE.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

struct HKWarpLUT
{
	double OriginLon = 0.0;
	double OriginLat = 0.0;
	double MetersPerDegLon = 1.0;
	double MetersPerDegLat = 1.0;
	double HarbourW = 1.0;
	double X0 = 0.0;
	double XStep = 1.0;
	double Y0 = 0.0;
	double YStep = 1.0;
	std::vector<double> G;
	std::vector<double> H;
	std::vector<double> A;
	std::vector<double> YC;
	bool bValid = false;
};

inline double HKWarpLerp(double Origin, double Step, const std::vector<double>& Values, double X)
{
	if (Values.empty())
	{
		return 0.0;
	}
	if (Values.size() == 1)
	{
		return Values[0];
	}
	const double MaxX = Origin + Step * static_cast<double>(Values.size() - 1);
	if (X <= Origin)
	{
		return Values.front();
	}
	if (X >= MaxX)
	{
		return Values.back();
	}
	const double F = (X - Origin) / Step;
	int Index = static_cast<int>(F);
	if (Index < 0)
	{
		Index = 0;
	}
	if (Index > static_cast<int>(Values.size()) - 2)
	{
		Index = static_cast<int>(Values.size()) - 2;
	}
	const double T = F - static_cast<double>(Index);
	return Values[static_cast<size_t>(Index)] * (1.0 - T) + Values[static_cast<size_t>(Index) + 1] * T;
}

inline void HKWarpRealToGame(const HKWarpLUT& Lut, double X, double Y, double& OutGameX, double& OutGameY)
{
	const double HV = HKWarpLerp(Lut.Y0, Lut.YStep, Lut.H, Y);
	const double AV = HKWarpLerp(Lut.X0, Lut.XStep, Lut.A, X);
	const double YC = HKWarpLerp(Lut.X0, Lut.XStep, Lut.YC, X);
	const double W = (Lut.HarbourW > 1e-6) ? Lut.HarbourW : 1.0;
	OutGameX = HKWarpLerp(Lut.X0, Lut.XStep, Lut.G, X);
	OutGameY = HV + AV * std::tanh((Y - YC) / W) - AV * std::tanh((0.0 - YC) / W);
}

inline void HKWarpLonLatToGameM(const HKWarpLUT& Lut, double Lon, double Lat, double& OutGameX, double& OutGameY)
{
	const double X = (Lon - Lut.OriginLon) * Lut.MetersPerDegLon;
	const double Y = (Lat - Lut.OriginLat) * Lut.MetersPerDegLat;
	HKWarpRealToGame(Lut, X, Y, OutGameX, OutGameY);
}

inline double HKWarpInvertLut(double Origin, double Step, const std::vector<double>& Values, double Target)
{
	if (Values.empty())
	{
		return Origin;
	}
	if (Target <= Values.front())
	{
		return Origin;
	}
	if (Target >= Values.back())
	{
		return Origin + Step * static_cast<double>(Values.size() - 1);
	}
	int Lo = 0;
	int Hi = static_cast<int>(Values.size()) - 1;
	while (Hi - Lo > 1)
	{
		const int Mid = (Lo + Hi) / 2;
		if (Values[static_cast<size_t>(Mid)] <= Target)
		{
			Lo = Mid;
		}
		else
		{
			Hi = Mid;
		}
	}
	const double Span = Values[static_cast<size_t>(Hi)] - Values[static_cast<size_t>(Lo)];
	const double T = (Span != 0.0) ? (Target - Values[static_cast<size_t>(Lo)]) / Span : 0.0;
	return Origin + Step * (static_cast<double>(Lo) + T);
}

inline void HKWarpGameToRealM(const HKWarpLUT& Lut, double GameX, double GameY, double& OutX, double& OutY)
{
	OutX = HKWarpInvertLut(Lut.X0, Lut.XStep, Lut.G, GameX);
	double Lo = Lut.Y0;
	double Hi = Lut.Y0 + Lut.YStep * static_cast<double>(Lut.H.empty() ? 0 : Lut.H.size() - 1);
	for (int Iteration = 0; Iteration < 60; ++Iteration)
	{
		const double Mid = 0.5 * (Lo + Hi);
		double MidX = 0.0;
		double MidY = 0.0;
		HKWarpRealToGame(Lut, OutX, Mid, MidX, MidY);
		if (MidY < GameY)
		{
			Lo = Mid;
		}
		else
		{
			Hi = Mid;
		}
	}
	OutY = 0.5 * (Lo + Hi);
}

inline void HKWarpGameMToLonLat(const HKWarpLUT& Lut, double GameX, double GameY, double& OutLon, double& OutLat)
{
	double X = 0.0;
	double Y = 0.0;
	HKWarpGameToRealM(Lut, GameX, GameY, X, Y);
	OutLon = Lut.OriginLon + X / Lut.MetersPerDegLon;
	OutLat = Lut.OriginLat + Y / Lut.MetersPerDegLat;
}

inline bool HKWarpReadExact(FILE* File, void* Dest, size_t Bytes, std::string& OutError)
{
	if (std::fread(Dest, 1, Bytes, File) != Bytes)
	{
		OutError = "unexpected end of warp lut";
		return false;
	}
	return true;
}

inline bool HKWarpLoadFile(const char* Path, HKWarpLUT& OutLut, std::string& OutError)
{
	OutLut = HKWarpLUT();
#if defined(_MSC_VER)
	FILE* File = nullptr;
	if (fopen_s(&File, Path, "rb") != 0)
	{
		File = nullptr;
	}
#else
	FILE* File = std::fopen(Path, "rb");
#endif
	if (!File)
	{
		OutError = std::string("cannot open warp lut: ") + Path;
		return false;
	}
	char Magic[8] = {};
	if (!HKWarpReadExact(File, Magic, 8, OutError) || std::memcmp(Magic, "HKWARP01", 8) != 0)
	{
		std::fclose(File);
		if (OutError.empty())
		{
			OutError = "warp lut magic mismatch";
		}
		return false;
	}
	std::uint32_t Version = 0;
	if (!HKWarpReadExact(File, &Version, 4, OutError) || Version != 1u)
	{
		std::fclose(File);
		if (OutError.empty())
		{
			OutError = "unsupported warp lut version";
		}
		return false;
	}
	double Header[6] = {};
	if (!HKWarpReadExact(File, Header, sizeof(Header), OutError))
	{
		std::fclose(File);
		return false;
	}
	OutLut.OriginLon = Header[0];
	OutLut.OriginLat = Header[1];
	OutLut.MetersPerDegLon = Header[2];
	OutLut.MetersPerDegLat = Header[3];
	OutLut.HarbourW = Header[4];
	OutLut.X0 = Header[5];
	if (!HKWarpReadExact(File, &OutLut.XStep, 8, OutError))
	{
		std::fclose(File);
		return false;
	}
	std::uint32_t NX = 0;
	if (!HKWarpReadExact(File, &NX, 4, OutError))
	{
		std::fclose(File);
		return false;
	}
	if (!HKWarpReadExact(File, &OutLut.Y0, 8, OutError) || !HKWarpReadExact(File, &OutLut.YStep, 8, OutError))
	{
		std::fclose(File);
		return false;
	}
	std::uint32_t NY = 0;
	if (!HKWarpReadExact(File, &NY, 4, OutError))
	{
		std::fclose(File);
		return false;
	}
	if (NX < 2 || NY < 2 || NX > 200000 || NY > 200000)
	{
		std::fclose(File);
		OutError = "warp lut size out of range";
		return false;
	}
	auto ReadArray = [&](std::uint32_t Count, std::vector<double>& Dest) -> bool
	{
		Dest.resize(Count);
		return HKWarpReadExact(File, Dest.data(), sizeof(double) * Count, OutError);
	};
	const bool bOk = ReadArray(NX, OutLut.G) && ReadArray(NY, OutLut.H) && ReadArray(NX, OutLut.A) && ReadArray(NX, OutLut.YC);
	std::fclose(File);
	OutLut.bValid = bOk;
	return bOk;
}
