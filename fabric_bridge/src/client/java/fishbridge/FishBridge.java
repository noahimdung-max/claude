package fishbridge;

import com.mojang.blaze3d.platform.InputConstants;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Queue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.item.ItemStack;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 마크 낚시 매크로 연결 모드.
 *
 * 마크 26.x(SDL)는 창이 뒤에 있으면 다른 프로그램이 보낸 키(Shift·E)를 버림 -> 매크로가 백그라운드 모드에서 미니게임을 못 함.
 * 이 모드는 127.0.0.1:47321 에서 한 줄 명령을 받아 게임 안에서 직접 처리함 (창이 앞이든 뒤든 됨).
 *
 *   ping                 -> 모드 정보
 *   sneak 1|0            -> 웅크리기 누름/뗌. 누르고 있으려면 1.5초 안에 다시 'sneak 1' (매크로가 꺼지면 알아서 뗌)
 *   use / attack         -> 우클릭 / 좌클릭 한 번
 *   press e|esc|1..9     -> 인벤 열기 / 열린 화면 닫기(게임 화면이면 아무것도 안 함) / 핫바 칸 고르기
 *   inv N                -> 빈칸 수·36칸 빈칸 여부·들고 있는 칸·N번 칸(0=들고 있는 칸) 내구도
 *   state                -> 창이 앞인지, 열린 화면
 *
 * 답은 한 줄 JSON: {"ok":true,...} 또는 {"ok":false,"err":"..."}
 */
public class FishBridge implements ClientModInitializer {
	public static final int PORT = 47321;
	public static final Logger LOG = LoggerFactory.getLogger("fishbridge");
	private static final long SNEAK_HOLD_MS = 1500;

	private static final Queue<Task> TASKS = new ConcurrentLinkedQueue<>();
	private static volatile boolean sneakWant;
	private static volatile long sneakUntil;
	private static boolean sneakApplied;
	private static final java.util.concurrent.atomic.AtomicInteger CLIENTS = new java.util.concurrent.atomic.AtomicInteger();

	/** 매크로가 연결돼 있나 (연결된 동안은 창이 뒤로 가도 일시정지 안 함). */
	public static boolean macroConnected() {
		return CLIENTS.get() > 0;
	}

	private record Task(Function<Minecraft, String> work, CompletableFuture<String> result) {}

	@Override
	public void onInitializeClient() {
		Thread t = new Thread(FishBridge::serve, "fishbridge-server");
		t.setDaemon(true);
		t.start();
	}

	// ---------------- 게임 쪽 (매 틱, 게임 스레드) ----------------

	public static void onTick(Minecraft mc) {
		Task task;
		while ((task = TASKS.poll()) != null) {
			try {
				task.result().complete(task.work().apply(mc));
			} catch (Throwable e) {
				task.result().complete(err(e.getClass().getSimpleName() + ": " + e.getMessage()));
			}
		}
		boolean want = sneakWant && System.currentTimeMillis() < sneakUntil;
		if (!want) {
			sneakWant = false;
		}
		if (want || sneakApplied) {
			setSneak(mc, want);
			sneakApplied = want;
		}
	}

	/** 웅크리기 '누르기'·'토글' 설정 둘 다: 원하는 상태가 되게. (토글이면 setDown(true) 가 상태를 뒤집음) */
	private static void setSneak(Minecraft mc, boolean want) {
		KeyMapping k = mc.options.keyShift;
		if (mc.options.toggleCrouch().get()) {
			if (k.isDown() != want) {
				k.setDown(true);
			}
		} else {
			k.setDown(want);
		}
	}

	private static void click(KeyMapping k) {
		KeyMapping.click(InputConstants.getKey(k.saveString()));
	}

	private static String run(Minecraft mc, String cmd, String arg) {
		LocalPlayer p = mc.player;
		switch (cmd) {
			case "use":
				if (p == null) return err("월드에 안 들어가 있음");
				click(mc.options.keyUse);
				return ok("");
			case "attack":
				if (p == null) return err("월드에 안 들어가 있음");
				click(mc.options.keyAttack);
				return ok("");
			case "press":
				return press(mc, p, arg);
			case "inv":
				return inventory(p, arg);
			case "state": {
				Screen s = mc.gui.screen();
				return ok("\"focused\":" + mc.isWindowActive() + ",\"screen\":" + (s == null ? "null" : q(s.getClass().getSimpleName()))
					+ ",\"paused\":" + (s != null && s.isPauseScreen()) + ",\"inWorld\":" + (p != null)
					+ ",\"sneaking\":" + (p != null && p.isShiftKeyDown()) + ",\"bobber\":" + (p != null && p.fishing != null));
			}
			case "devcmd":                                    // 개발용 시험에서만 (-Dfishbridge.dev=true)
				if (!Boolean.getBoolean("fishbridge.dev")) return err("개발용 명령");
				if (p == null) return err("월드에 안 들어가 있음");
				p.connection.sendCommand(arg);
				return ok("");
			default:
				return err("모르는 명령: " + cmd);
		}
	}

	private static String press(Minecraft mc, LocalPlayer p, String key) {
		if ("e".equals(key)) {
			if (p == null) return err("월드에 안 들어가 있음");
			click(mc.options.keyInventory);
			return ok("");
		}
		if ("esc".equals(key)) {
			Screen s = mc.gui.screen();
			if (s != null) {
				s.onClose();                                  // 인벤·상자는 서버에도 닫았다고 알림, 일시정지 메뉴는 게임으로 돌아감
			}
			return ok("\"closed\":" + (s == null ? "null" : q(s.getClass().getSimpleName())));
		}
		if (key != null && key.length() == 1 && key.charAt(0) >= '1' && key.charAt(0) <= '9') {
			if (p == null) return err("월드에 안 들어가 있음");
			p.getInventory().setSelectedSlot(key.charAt(0) - '1');
			return ok("");
		}
		return err("모르는 키: " + key);
	}

	/** 매크로의 인벤 칸 순서와 같게: 위 3줄(9~35번) 다음 핫바(0~8번). */
	private static String inventory(LocalPlayer p, String arg) {
		if (p == null) return err("월드에 안 들어가 있음");
		Inventory inv = p.getInventory();
		StringBuilder map = new StringBuilder("[");
		int empty = 0;
		for (int i = 0; i < Inventory.INVENTORY_SIZE; i++) {
			int idx = i < 27 ? i + 9 : i - 27;
			boolean e = inv.getItem(idx).isEmpty();
			if (e) empty++;
			map.append(i == 0 ? "" : ",").append(e);
		}
		map.append(']');
		int sel = inv.getSelectedSlot() + 1;
		int slot = 0;
		try {
			slot = arg == null || arg.isEmpty() ? 0 : Integer.parseInt(arg);
		} catch (NumberFormatException ignored) {
		}
		ItemStack st = inv.getItem((slot >= 1 && slot <= 9 ? slot : sel) - 1);
		String dur = "null";
		if (st.isDamageableItem()) {
			int max = st.getMaxDamage();
			dur = "[" + (max - st.getDamageValue()) + "," + max + "]";
		}
		return ok("\"empty\":" + empty + ",\"map\":" + map + ",\"sel\":" + sel + ",\"dur\":" + dur);
	}

	// ---------------- 연결 쪽 (127.0.0.1 만) ----------------

	private static void serve() {
		try (ServerSocket server = new ServerSocket(PORT, 4, InetAddress.getLoopbackAddress())) {
			LOG.info("[fishbridge] 127.0.0.1:{} 에서 매크로 연결 기다리는 중", PORT);
			while (true) {
				Socket s = server.accept();
				Thread t = new Thread(() -> handle(s), "fishbridge-client");
				t.setDaemon(true);
				t.start();
			}
		} catch (Exception e) {
			LOG.error("[fishbridge] 연결 서버를 못 열었어 (포트 {} 를 다른 프로그램이 쓰는 중?)", PORT, e);
		}
	}

	private static void handle(Socket s) {
		CLIENTS.incrementAndGet();
		try (s; BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8))) {
			s.setTcpNoDelay(true);
			OutputStream out = s.getOutputStream();
			String line;
			while ((line = in.readLine()) != null) {
				String ans = answer(line.trim());
				out.write((ans + "\n").getBytes(StandardCharsets.UTF_8));
				out.flush();
			}
		} catch (Exception e) {
			// 연결 끊김 (아래에서 정리)
		} finally {
			// 매크로가 끊음: 누르고 있던 웅크리기는 다음 틱에 뗌, 자동 일시정지는 다시 원래대로
			sneakWant = false;
			CLIENTS.decrementAndGet();
		}
	}

	private static String answer(String line) {
		String[] parts = line.split("\\s+", 2);
		String cmd = parts[0].toLowerCase();
		String arg = parts.length > 1 ? parts[1].trim().toLowerCase() : "";
		switch (cmd) {
			case "ping": {
				String mcv = FabricLoader.getInstance().getModContainer("minecraft")
					.map(m -> m.getMetadata().getVersion().getFriendlyString()).orElse("?");
				String ver = FabricLoader.getInstance().getModContainer("fishbridge")
					.map(m -> m.getMetadata().getVersion().getFriendlyString()).orElse("?");
				return ok("\"mod\":\"fishbridge\",\"ver\":" + q(ver) + ",\"mc\":" + q(mcv));
			}
			case "sneak":
				if ("1".equals(arg)) {
					sneakUntil = System.currentTimeMillis() + SNEAK_HOLD_MS;
					sneakWant = true;
				} else {
					sneakWant = false;
				}
				return ok("");
			case "":
				return err("빈 명령");
			default: {
				CompletableFuture<String> f = new CompletableFuture<>();
				TASKS.add(new Task(mc -> run(mc, cmd, arg), f));
				try {
					return f.get(2, TimeUnit.SECONDS);
				} catch (Exception e) {
					return err("게임이 2초 안에 처리 못 함 (로딩 중?)");
				}
			}
		}
	}

	private static String ok(String fields) {
		return fields.isEmpty() ? "{\"ok\":true}" : "{\"ok\":true," + fields + "}";
	}

	private static String err(String msg) {
		return "{\"ok\":false,\"err\":" + q(msg) + "}";
	}

	private static String q(String s) {
		StringBuilder b = new StringBuilder("\"");
		for (char c : s.toCharArray()) {
			if (c == '"' || c == '\\') b.append('\\').append(c);
			else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
			else b.append(c);
		}
		return b.append('"').toString();
	}
}
