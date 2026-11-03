// C ABI over shared/hk_drive_assist.h for the offline model (tools/drive_model/model.py).
// The Python side builds its ctypes structs by parsing the header, and checks the sizes here.
#include "hk_drive_assist.h"

extern "C"
{
void hk_sizes(int* Out)
{
	Out[0] = static_cast<int>(sizeof(hkdrive::Params));
	Out[1] = static_cast<int>(sizeof(hkdrive::State));
	Out[2] = static_cast<int>(sizeof(hkdrive::Input));
	Out[3] = static_cast<int>(sizeof(hkdrive::Output));
	Out[4] = static_cast<int>(sizeof(hkdrive::Memory));
}

void hk_defaults(hkdrive::Params* P, hkdrive::Memory* M)
{
	*P = hkdrive::Params();
	*M = hkdrive::Memory();
}

void hk_step(const hkdrive::Params* P, const hkdrive::State* S, const hkdrive::Input* In, hkdrive::Memory* M, float Dt, hkdrive::Output* Out)
{
	*Out = hkdrive::Step(*P, *S, *In, *M, Dt);
}
}
