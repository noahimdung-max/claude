package fishbridge.mixin;

import fishbridge.FishBridge;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(Minecraft.class)
public class MinecraftTickMixin {
	/** 매 틱 시작에: 매크로가 보낸 명령 실행 + 웅크리기 유지 (키 처리보다 먼저 되게 HEAD). */
	@Inject(method = "tick", at = @At("HEAD"))
	private void fishbridge$tick(CallbackInfo ci) {
		FishBridge.onTick((Minecraft) (Object) this);
	}

	/** 매크로가 연결돼 있는 동안은 '창이 뒤로 가면 일시정지'를 건너뜀 (메뉴가 열리면 낚싯대를 못 던짐). 설정값은 안 바꿈. */
	@Inject(method = "pauseIfInactive", at = @At("HEAD"), cancellable = true)
	private void fishbridge$noAutoPause(CallbackInfo ci) {
		if (FishBridge.macroConnected()) {
			ci.cancel();
		}
	}
}
