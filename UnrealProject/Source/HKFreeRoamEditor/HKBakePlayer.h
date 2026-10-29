#pragma once

#include "CoreMinimal.h"

namespace HKBakePlayer
{
	enum class EResult : uint8
	{
		/** DA_PlayerAvatar was written (with or without retargeted clips; see the log). */
		Written,
		/** Nothing to bake: player.json missing or unreadable, or no usable model. The game keeps the cube body. */
		NoModel,
		/**
		 * A real error: an engine API that is missing or has changed shape (e.g. UIKRetargetBatchOperation::RunBatchRetarget), or a retarget that
		 * produced nothing. Logged as Error; callers must fail the bake instead of shipping a
		 * chibi without animations.
		 */
		Failed,
	};

	/**
	 * Rebuilds /Game/HK/Player from data/config/player.json: imports the player model (VRM via
	 * VRM4U, or glb/gltf/fbx via Interchange), applies the figure materials, retargets the UAL
	 * clips onto it and writes DA_PlayerAvatar. Never touches the world map.
	 */
	EResult Bake();
}
