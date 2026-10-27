// Compares shared/hk_warp.h against golden samples written by tools/hkwarp/warp.py.
#include "hk_warp.h"

#include <cmath>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

int main(int argc, char** argv)
{
	if (argc != 3)
	{
		std::cerr << "usage: test_hk_warp warp_lut.bin golden.csv\n";
		return 2;
	}
	HKWarpLUT Lut;
	std::string Error;
	if (!HKWarpLoadFile(argv[1], Lut, Error))
	{
		std::cerr << Error << "\n";
		return 1;
	}
	std::ifstream Input(argv[2]);
	if (!Input)
	{
		std::cerr << "cannot open golden file\n";
		return 1;
	}
	std::string Line;
	std::getline(Input, Line);
	double MaxForward = 0.0;
	double MaxInverse = 0.0;
	int ForwardCount = 0;
	int InverseCount = 0;
	while (std::getline(Input, Line))
	{
		if (Line.empty())
		{
			continue;
		}
		std::stringstream Stream(Line);
		std::string Kind, A, B, C, D;
		std::getline(Stream, Kind, ',');
		std::getline(Stream, A, ',');
		std::getline(Stream, B, ',');
		std::getline(Stream, C, ',');
		std::getline(Stream, D, ',');
		if (Kind == "F")
		{
			const double Lon = std::stod(A);
			const double Lat = std::stod(B);
			const double ExpectX = std::stod(C);
			const double ExpectY = std::stod(D);
			double X = 0.0;
			double Y = 0.0;
			HKWarpLonLatToGameM(Lut, Lon, Lat, X, Y);
			MaxForward = std::max(MaxForward, std::abs(X - ExpectX));
			MaxForward = std::max(MaxForward, std::abs(Y - ExpectY));
			++ForwardCount;
		}
		else if (Kind == "I")
		{
			const double X = std::stod(A);
			const double Y = std::stod(B);
			const double ExpectLon = std::stod(C);
			const double ExpectLat = std::stod(D);
			double Lon = 0.0;
			double Lat = 0.0;
			HKWarpGameMToLonLat(Lut, X, Y, Lon, Lat);
			MaxInverse = std::max(MaxInverse, std::abs(Lon - ExpectLon));
			MaxInverse = std::max(MaxInverse, std::abs(Lat - ExpectLat));
			++InverseCount;
		}
	}
	std::cout << "forward samples " << ForwardCount << " max error m " << MaxForward << "\n";
	std::cout << "inverse samples " << InverseCount << " max error deg " << MaxInverse << "\n";
	if (ForwardCount < 10 || InverseCount < 10 || MaxForward > 1e-3 || MaxInverse > 2e-5)
	{
		std::cerr << "warp native check failed\n";
		return 1;
	}
	return 0;
}
