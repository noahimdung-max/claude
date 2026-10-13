"""낚시 기록 분석: macro.log (또는 메모리에 남긴 같은 기록)을 읽어서
- 몇 번 던져서 몇 마리 낚았고, 헛챔질(입질로 착각해서 낚싯줄을 당김)이 몇 번이었는지
- 시간이 어디에 쓰였는지 (입질 대기 / 미니게임 / 다음 던지기까지)
- 헛챔질이 어떤 판정 때문이었는지
를 보여주고 고칠 점을 알려줌.   python analysis.py macro.log
"""
import re
import statistics
import sys
from collections import Counter

LINE = re.compile(r"(\d\d):(\d\d):(\d\d)\.(\d+) \[(\w+)\] (\w+)\s+(.*)")


def parse_text(text):
    """macro.log 내용 -> [(초, 태그, 내용)]. 자정을 넘으면 시간이 이어지게."""
    events, day, last = [], 0, None
    for line in text.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + float("0." + m.group(4))
        if last is not None and t + day * 86400 < last - 3600:
            day += 1
        t += day * 86400
        last = t
        events.append((t, m.group(6), m.group(7)))
    return events


def split_cycles(events):
    """던지기 한 번 = 한 사이클. 시작/정지 사이에서는 끊어서 센다."""
    cycles, cur = [], None
    notes = Counter()
    for t, tag, msg in events:
        if tag == "BITE" and msg.startswith("입질 대기 시작"):
            if cur:
                cycles.append(cur)
            cur = {"start": t}
            m = re.search(r"모드=(\S+)", msg)
            cur["mode"] = m.group(1) if m else "?"
        elif msg.startswith("[시작]") or msg.startswith("[정지]") or tag == "START":
            if cur:
                cycles.append(cur)
                cur = None
        elif tag == "BITE" and msg.startswith("결과=") and cur is not None:
            cur["bite_t"] = t
            cur["bite_ok"] = msg.startswith("결과=입질")
            m = re.search(r"사유=(\S+)", msg)
            cur["reason"] = m.group(1) if m and m.group(1) != "-" else ("자막" if cur.get("mode") == "subtitle" else "-")
            m = re.search(r"자막최고=(\S+)", msg)
            cur["sub_max"] = m.group(1) if m else None
        elif cur is not None and "미니게임 시작" in msg:
            cur["mg0"] = t
        elif cur is not None and "미니게임 끝" in msg:
            cur["mg1"] = t
        elif cur is not None and "미니게임 안 뜸" in msg:
            cur["miss"] = t
        elif cur is not None and ("찌를 못 찾음" in msg or "입질 시간초과" in msg or "찌가 화면에서 사라짐" in msg):
            cur["nobite_why"] = ("찌를 못 찾음" if "못 찾음" in msg else "입질 시간초과" if "시간초과" in msg else "찌가 사라짐")
        if tag != "INFO":                                   # 같은 내용이 DEBUG 로도 남아서 INFO 만 셈
            continue
        if "오류 -> 복구 시도" in msg:
            notes["오류 복구"] += 1
        elif "[복구]" in msg:
            notes["창 닫기 복구"] += 1
        elif "툴팁 숫자 못 읽음" in msg or "인벤 창 모양" in msg:
            notes["인벤 확인 실패"] += 1
    if cur:
        cycles.append(cur)
    return cycles, notes


def _stats(a):
    return None if not a else {"mean": statistics.mean(a), "median": statistics.median(a), "min": min(a), "max": max(a), "n": len(a)}


def summarize(events):
    cycles, notes = split_cycles(events)
    caught = [c for c in cycles if "mg1" in c]
    false_ = [c for c in cycles if "miss" in c]
    nobite = [c for c in cycles if c.get("bite_ok") is False]
    done = [c for c in cycles if "mg1" in c or "miss" in c or c.get("bite_ok") is False]
    span = (events[-1][0] - events[0][0]) if len(events) > 1 else 0.0
    wait = [c["bite_t"] - c["start"] for c in caught if "bite_t" in c]
    mg = [c["mg1"] - c["mg0"] for c in caught if "mg0" in c]
    lat = [c["mg0"] - c["bite_t"] for c in caught if "mg0" in c and "bite_t" in c]
    gap = []
    for i in range(len(cycles) - 1):
        if "mg1" in cycles[i]:
            g = cycles[i + 1]["start"] - cycles[i]["mg1"]
            if 0 <= g < 60:
                gap.append(g)
    lost = [c["miss"] - c["start"] for c in false_]
    cfg = {}
    for t, tag, msg in events:
        if tag == "CONFIG":
            for k in ("left_click_cps", "bite_mode", "durability_stop_pct"):
                m = re.search(k + r"=(\S+?)(?:,|$)", msg)
                if m:
                    cfg[k] = m.group(1)
    reasons = Counter()
    for c in cycles:
        if c.get("bite_ok"):
            reasons[(c.get("reason", "-"), "caught" if "mg1" in c else "false" if "miss" in c else "?")] += 1
    nobite_why = Counter(c.get("nobite_why", "?") for c in nobite)
    total_lost = sum(lost)
    return {"cycles": len(cycles), "done": len(done), "caught": len(caught), "false": len(false_), "nobite": len(nobite),
            "span": span, "wait": _stats(wait), "mg": _stats(mg), "lat": _stats(lat), "gap": _stats(gap),
            "lost": total_lost, "lost_each": _stats(lost), "reasons": dict(reasons), "nobite_why": dict(nobite_why),
            "notes": dict(notes), "cfg": cfg}


def advice(s):
    out = []
    done = max(1, s["done"])
    fr = s["false"] / done
    if s["false"] and fr >= 0.08:
        share = s["lost"] / s["span"] if s["span"] else 0
        out.append(f"헛챔질이 {fr:.0%} ({s['false']}번) 이고 그 때문에 {s['lost']:.0f}초({share:.0%}) 를 버렸어.")
        by = Counter()
        for (why, res), n in s["reasons"].items():
            if res == "false":
                by[why] += n
        for why, n in by.most_common():
            if why.startswith("가라앉음(속도)"):
                out.append(f"  - '{why}' 로 잡힌 {n}번이 헛챔질: 예전 버전(v1.6.2~1.6.5)의 속도 규칙이 원인이야 -> v1.6.6 이상으로 업데이트")
            elif why.startswith("가라앉음(크기)") or why.startswith("가라앉음"):
                out.append(f"  - '{why}' {n}번: 찌가 평소에도 크게 출렁이는 곳이면 세부 탭 '입질: 찌가 이만큼(px) 내려가면' 을 올려봐")
            elif why.startswith("픽셀감소"):
                out.append(f"  - '{why}' {n}번: 파티클·물보라가 찌를 가렸을 수 있어 -> 마크 파티클 '최소', 찌 영역이 물만 덮는지 확인")
            elif why.startswith("물보라"):
                out.append(f"  - '{why}' {n}번: 흰 물보라를 입질로 착각 -> 파티클 '최소'")
            elif why == "자막":
                out.append(f"  - 자막 {n}번: 다른 소리 자막을 입질로 착각 -> 자막을 다시 지정하고 '자막 일치 기준' 올려봐")
            else:
                out.append(f"  - '{why}' {n}번")
    nb = s["nobite"] / done
    if s["nobite"] and nb >= 0.08:
        parts = ", ".join(f"{k} {v}번" for k, v in s["nobite_why"].items())
        out.append(f"입질을 못 잡고 다시 던진 게 {nb:.0%} ({parts}).")
        if s["nobite_why"].get("찌를 못 찾음"):
            out.append("  - '찌를 못 찾음': 찌 영역이 물을 덮는지, 어두운지, 리소스팩을 쓰면 켜져 있는지 확인 (찌 지정하기 > 확인 화면의 찌 색)")
    if s["gap"] and s["gap"]["mean"] > 2.0:
        out.append(f"미니게임 끝~다음 던지기 사이가 평균 {s['gap']['mean']:.1f}초: 세부 탭 '다시 던지기 전 대기' 와 '미니게임 끝났다고 보는 시간' 을 확인")
    n = s["notes"]
    if n.get("인벤 확인 실패"):
        out.append(f"인벤 확인이 {n['인벤 확인 실패']}번 실패: 정밀 내구도를 못 읽었어 (F3+H 켜져 있는지, v1.6.6 이상인지)")
    if n.get("오류 복구"):
        out.append(f"오류로 자동 복구한 게 {n['오류 복구']}번: error.txt 를 보내줘")
    if n.get("창 닫기 복구"):
        out.append(f"마크에 메뉴가 떠서 닫은 게 {n['창 닫기 복구']}번")
    return out


def hints(s):
    """문제는 아니지만 시간을 줄이려고 해볼 만한 것."""
    out = []
    if s["mg"] and s["mg"]["n"] >= 5:
        cps = s["cfg"].get("left_click_cps")
        out.append(f"미니게임이 평균 {s['mg']['mean']:.1f}초 걸려 (전체의 약 {s['mg']['mean'] / max(1.0, s['mg']['mean'] + (s['wait'] or {'mean': 0})['mean'] + (s['gap'] or {'mean': 0})['mean']):.0%})."
                   + (f" 지금 초당 클릭 {cps}번인데, 올려보고 이 평균이 줄어드는지 비교해봐 (서버가 허용하는 범위에서)." if cps else ""))
    if s["wait"] and s["wait"]["n"] >= 5:
        out.append(f"입질을 기다리는 시간({s['wait']['mean']:.1f}초)이 가장 큰데, 이건 서버가 정하는 거라 매크로로는 못 줄여.")
    return out


def _f(st, key="mean"):
    return "-" if not st else f"{st[key]:.1f}초"


def report(events):
    """사람이 읽는 분석 글."""
    if len(events) < 5:
        return "분석할 기록이 아직 없어. 낚시를 한참 돌린 뒤에 눌러줘 (세부 탭 '로그 남기기'를 켜두면 파일로도 남아)."
    s = summarize(events)
    if not s["done"]:
        return "던져서 끝난 기록이 아직 없어."
    done = s["done"]
    L = [f"던진 횟수 {done}번  ->  낚음 {s['caught']} ({s['caught'] / done:.0%}) / 헛챔질 {s['false']} ({s['false'] / done:.0%})"
         f" / 입질 못 잡음 {s['nobite']} ({s['nobite'] / done:.0%})"]
    if s["span"] > 60 and s["caught"]:
        L.append(f"걸린 시간 {s['span'] / 60:.0f}분 -> 시간당 약 {s['caught'] / s['span'] * 3600:.0f}마리")
        if s["lost"] > 0:
            ideal = s["caught"] / max(1.0, s["span"] - s["lost"]) * 3600
            L.append(f"헛챔질로 버린 시간 {s['lost']:.0f}초 ({s['lost'] / s['span']:.0%}) -> 없었다면 시간당 약 {ideal:.0f}마리")
    L.append("")
    L.append("1회 평균 (낚은 것만)")
    L.append(f"  던진 뒤 입질까지 {_f(s['wait'])} (서버가 정함)   입질~미니게임 시작 {_f(s['lat'])}")
    L.append(f"  미니게임 {_f(s['mg'])} (최소 {_f(s['mg'], 'min')})   미니게임 끝~다음 던지기 {_f(s['gap'])}")
    if s["reasons"]:
        L.append("")
        L.append("입질 판정 사유별 결과")
        by = {}
        for (why, res), n in s["reasons"].items():
            by.setdefault(why, Counter())[res] += n
        for why, c in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
            tot = sum(c.values())
            L.append(f"  {why}: {tot}번 -> 낚음 {c['caught']} / 헛챔질 {c['false']}" + (f" / 확인안됨 {c['?']}" if c["?"] else ""))
    tips = advice(s)
    L.append("")
    L.append("고칠 점" if tips else "눈에 띄는 문제 없음")
    L.extend(("  " + t if not t.startswith("  ") else t) for t in tips)
    hs = hints(s)
    if hs:
        L.append("")
        L.append("참고")
        L.extend("  " + h for h in hs)
    return "\n".join(L)


def report_file(path):
    from pathlib import Path
    p = Path(path)
    text = ""
    old = p.with_name(p.name + ".1")                       # 로그가 1MB 넘어서 교체된 앞부분
    for q in (old, p):
        if q.exists():
            text += q.read_text(encoding="utf-8", errors="ignore") + "\n"
    return report(parse_text(text))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python analysis.py macro.log")
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8")
    print(report_file(sys.argv[1]))
