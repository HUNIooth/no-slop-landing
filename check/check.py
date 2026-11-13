#!/usr/bin/env python3
"""소개 페이지 점검.

사용
  python3 check/check.py <주소>                  채운 페이지를 점검한다
  python3 check/check.py <주소> --placeholders-ok  본처럼 대괄호 자리가 남아 있어도 실패로 치지 않는다

준비
  pip install playwright
  설치된 Chrome을 쓴다. Chrome이 없으면 `playwright install chromium` 뒤에 다시 실행한다.
  주소는 http(s)여야 한다. 파일을 바로 열지 말고 `python3 -m http.server`로 띄운다.

보는 것
  1 너비 아홉 가지(320~1440px): 가로 넘침, 44px보다 작은 누름 영역, 없는 곳을 가리키는 링크, 콘솔 오류
  2 글: 줄표, 채우지 않은 대괄호 자리, h1 개수, 제목 단계 건너뜀, lang과 title
  3 그림: 너비·높이 속성, 화면 배율 2.5에서 원본보다 크게 늘어난 그림
  4 화면 채움: 넓은 화면 일곱 가지에서 화면 하나를 넘는 구획
  5 키보드: Tab으로 닿는 곳마다 초점 테두리가 보이는지
  6 움직임 줄이기 설정: 숨은 채 남는 내용이 없는지

실패가 하나라도 있으면 종료 코드 1로 끝난다. 사람 눈으로 볼 것은 GUIDE.md 9번에 있다.
"""
import sys

from playwright.sync_api import sync_playwright

WIDTHS = (320, 360, 390, 600, 768, 960, 1024, 1280, 1440)
SCREENS = ((1100, 700), (1280, 720), (1366, 768), (1440, 900), (1536, 867), (1920, 1080), (2560, 1440))

PAGE_FACTS = """() => {
  const de = document.documentElement, vw = innerWidth;
  const seen = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'; };
  const label = e => (e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 14);
  const small = [...document.querySelectorAll('a[href],button')].filter(seen)
    .filter(e => { const r = e.getBoundingClientRect(); return r.height < 44 || r.width < 44; })
    .map(e => label(e) + ' ' + Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height));
  const dead = [...document.querySelectorAll('a[href^="#"]')].map(a => a.getAttribute('href'))
    .filter(h => h === '#' || !document.querySelector(h));
  const levels = [...document.querySelectorAll('h1,h2,h3,h4')].map(h => +h.tagName[1]);
  const text = document.body.innerText;
  return {
    overflow: de.scrollWidth > vw, scrollWidth: de.scrollWidth, small, dead,
    h1: document.querySelectorAll('h1').length,
    skipped: levels.some((n, i) => i > 0 && n - levels[i - 1] > 1),
    dashes: (text.match(/[\\u2014\\u2013]/g) || []).length,
    placeholders: [...new Set(text.match(/\\[[^\\]\\n]{1,60}\\]/g) || [])],
    unsized: [...document.querySelectorAll('img,video')].filter(m => !m.getAttribute('width') || !m.getAttribute('height')).map(m => m.getAttribute('src') || m.tagName),
    lang: de.getAttribute('lang') || '', title: document.title,
  };
}"""

BLURRY = """() => [...document.images].filter(i => i.complete && i.naturalWidth > 0)
  .map(i => ({ src: (i.getAttribute('src') || '').split('/').pop(), have: i.naturalWidth, need: Math.round(i.getBoundingClientRect().width * devicePixelRatio) }))
  .filter(i => i.need > 0 && i.have < i.need * .98)"""

SECTIONS = """() => {
  const top = document.querySelector('header') ? document.querySelector('header').getBoundingClientRect().height : 0;
  const room = innerHeight - top;
  return { snap: getComputedStyle(document.documentElement).scrollSnapType,
           tall: [...document.querySelectorAll('main > section')].map((s, i) => [s.id || ('구획 ' + (i + 1)), Math.round(s.getBoundingClientRect().height)]).filter(x => x[1] > room + 1),
           room: Math.round(room) };
}"""

HIDDEN = """() => [...document.querySelectorAll('main *')]
  .filter(e => e.children.length === 0 && (e.textContent || '').trim() && e.getBoundingClientRect().width > 0 && !e.closest('.sr'))
  .filter(e => { for (let n = e; n && n !== document.body; n = n.parentElement) if (parseFloat(getComputedStyle(n).opacity) < .05) return true; return false; })
  .map(e => e.textContent.trim().slice(0, 20))"""

results = []


def record(ok, name, detail=""):
    results.append((ok, name, detail))
    print(f"{'통과' if ok else '실패'} | {name}" + (f" | {detail}" if detail else ""))


def scroll_through(page):
    """늦게 불러오는 그림까지 뜨도록 끝까지 내려갔다가 올라온다."""
    height = page.evaluate("document.documentElement.scrollHeight")
    for y in range(0, height, 600):
        page.evaluate(f"window.scrollTo({{top:{y},behavior:'instant'}})")
        page.wait_for_timeout(120)
    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
    page.wait_for_timeout(300)


def main(url, placeholders_ok):
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)

        # 1, 2: 너비별 사실
        overflow, small, dead, errors, facts = [], set(), set(), [], None
        for width in WIDTHS:
            phone = width < 700
            ctx = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone)
            page = ctx.new_page()
            page.on("console", lambda m: errors.append(m.text[:100]) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)[:100]))
            page.goto(url, wait_until="load")
            page.wait_for_timeout(400)
            facts = page.evaluate(PAGE_FACTS)
            if facts["overflow"]:
                overflow.append(f"{width}px에서 {facts['scrollWidth']}px")
            small.update(facts["small"])
            dead.update(facts["dead"])
            ctx.close()
        record(not overflow, "가로 넘침 없음(너비 아홉 가지)", ", ".join(overflow))
        record(not small, "누름 영역이 모두 44px 이상", ", ".join(sorted(small)[:6]))
        record(not dead, "없는 곳을 가리키는 링크 없음", ", ".join(sorted(dead)))
        record(not errors, "콘솔 오류 없음", "; ".join(errors[:3]))
        record(facts["dashes"] == 0, "줄표 없음", f"{facts['dashes']}개")
        if placeholders_ok:
            print(f"참고 | 대괄호 자리 {len(facts['placeholders'])}종 (--placeholders-ok라 실패로 치지 않음)")
        else:
            record(not facts["placeholders"], "채우지 않은 대괄호 자리 없음", ", ".join(facts["placeholders"][:5]))
        record(facts["h1"] == 1 and not facts["skipped"], "h1 하나, 제목 단계 건너뜀 없음", f"h1 {facts['h1']}개")
        record(bool(facts["lang"]) and bool(facts["title"].strip()), "lang과 title 있음")
        record(not facts["unsized"], "그림·영상에 너비와 높이 있음", ", ".join(facts["unsized"][:5]))

        # 3: 배율 2.5에서 그림 선명도
        ctx = browser.new_context(viewport={"width": 1536, "height": 867}, device_scale_factor=2.5)
        page = ctx.new_page()
        page.goto(url, wait_until="load")
        scroll_through(page)
        blurry = page.evaluate(BLURRY)
        record(not blurry, "배율 2.5에서 원본보다 크게 늘어난 그림 없음",
               ", ".join(f"{b['src']} 원본 {b['have']}px, 필요 {b['need']}px" for b in blurry[:5]))
        ctx.close()

        # 4: 화면 채움
        tall, snap = [], "none"
        for width, height in SCREENS:
            ctx = browser.new_context(viewport={"width": width, "height": height})
            page = ctx.new_page()
            page.goto(url, wait_until="load")
            page.wait_for_timeout(300)
            info = page.evaluate(SECTIONS)
            if info["snap"] != "none":
                snap = info["snap"]
                tall += [f"{width}x{height}에서 {name} {h}px(남는 높이 {info['room']}px)" for name, h in info["tall"]]
            ctx.close()
        if snap == "none":
            print("참고 | 구획 단위 멈춤을 쓰지 않는 페이지라 화면 채움은 보지 않음")
        else:
            record(not tall, "화면 하나를 넘는 구획 없음(화면 크기 일곱 가지)", "; ".join(tall[:4]))

        # 5: 키보드
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(url, wait_until="load")
        count = page.evaluate("document.querySelectorAll('a[href],button,video,input,select,textarea,summary').length")
        reached, no_ring = 0, []
        for _ in range(count + 3):
            page.keyboard.press("Tab")
            f = page.evaluate("""() => { const e = document.activeElement, s = getComputedStyle(e);
                return { tag: e.tagName, text: (e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 14), ring: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2 }; }""")
            if f["tag"] == "BODY":
                break
            reached += 1
            if f["tag"] != "VIDEO" and not f["ring"]:
                no_ring.append(f["text"])
        record(reached > 0 and not no_ring, f"Tab으로 {reached}곳에 닿고 초점 테두리가 보임", ", ".join(no_ring[:5]))
        ctx.close()

        # 6: 움직임 줄이기
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(url, wait_until="load")
        page.wait_for_timeout(500)
        hidden = page.evaluate(HIDDEN)
        record(not hidden, "움직임 줄이기 설정에서 숨은 내용 없음", ", ".join(hidden[:5]))
        ctx.close()
        browser.close()

    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)}건 통과, {len(failed)}건 실패")
    return 1 if failed else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    sys.exit(main(args[0], "--placeholders-ok" in sys.argv))
