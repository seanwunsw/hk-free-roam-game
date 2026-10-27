#pragma once

#include "CoreMinimal.h"

namespace HKBakePlayer
{
	/**
	 * Rebuilds /Game/HK/Player from data/config/player.json: imports the player model (VRM via
	 * VRM4U, or glb/gltf/fbx via Interchange), applies the figure materials, retargets the UAL
	 * clips onto it and writes DA_PlayerAvatar. Returns false when no avatar was written; the
	 * game then keeps the cube body. Never touches the world map.
	 */
	bool Bake();
}
