# CDMS-Agent ???꾨줈?앺듃 而⑦뀓?ㅽ듃 (Claude ?몄닔?멸퀎??

> ???몄뀡?먯꽌 ???뚯씪???쎌쑝硫?利됱떆 肄붾뵫???쒖옉?????덉뒿?덈떎.

---

## 1. ?꾨줈?앺듃 紐⑹쟻

Maven CDMS(?꾩긽?쒗뿕 ?곗씠??愿由??쒖뒪?? 釉뚮씪?곗? ?몄뀡??Python/Jupyter?먯꽌 ?먭꺽?쇰줈 議곗옉?섎뒗 RPA ?꾧뎄.
二??⑸룄: **DVS(Data Validation Specification) Excel???쎌뼱 CDMS???곗씠?곕? ?낅젰?섍퀬 Query 諛쒖깮 ?щ?瑜??먮룞 寃利앺븳??**

---

## 2. ?쒖뒪???꾪궎?띿쿂

```
Jupyter / Python script
    ?? HTTP (localhost:3100)
    ??CDM Agent Daemon  (Next.js, ?ы듃 3100)
    ?? WebSocket / polling
    ??Chrome Extension  (service-worker + content-script)
    ?? Chrome Runtime Message
    ??browser-runner-core.js  (CDMS ?섏씠吏?먯꽌 ?ㅽ뻾?섎뒗 DOM 議곗옉 肄붿뼱)
```

### 寃쎈줈
| 而댄룷?뚰듃 | 寃쎈줈 |
|---|---|
| Python ?대씪?댁뼵???⑦궎吏 | `src/cdm_agent_client/` |
| Chrome Extension ?뚯뒪 | `extension/` |
| DVS ?먮룞??紐⑤뱢 | `src/cdm_agent_client/dvs/` |

---

## 3. 二쇱슂 湲곗닠 ?쒖빟 (諛섎뱶???숈?)

### 3-1. Fluent UI ?쇰뵒?ㅻ쾭????`isTrusted: false` 臾몄젣
- CDMS??Fluent UI瑜??ъ슜?섎ŉ, ?쇰뵒?ㅻ쾭?쇱씠 `input[type='radio']`媛 ?꾨땶
  **`.cr-clearable-radio-buttons input[type='checkbox']`** 濡??뚮뜑??- JS濡?`dispatchEvent(new MouseEvent(...))` ?섎㈃ `isTrusted: false`??Fluent UI媛 臾댁떆??- **?닿껐梨?*: CDP(Chrome DevTools Protocol)瑜??듯븳 `isTrusted: true` 留덉슦???대깽??二쇱엯
  ??`extension/browser-runner-core.js`??`selectRadio()` ?⑥닔媛 ?ㅼ젣 ?대┃ 醫뚰몴瑜?援ы빐
  `chrome.debugger.sendCommand('Input.dispatchMouseEvent', ...)` 濡?泥섎━
- 愿???⑥닔: `getRadioLabelCoords()`, `findOptionInput()` ????됲꽣媛
  `.cr-clearable-radio-buttons input[type='checkbox']` ?꾩뿉 二쇱쓽

### 3-2. React SPA ?ㅻ퉬寃뚯씠????`navigateToUrl` ?ㅽ깘
- CDMS??React SPA?대?濡?`location.href =` 蹂寃???frame???쒓굅?섏? ?딆쓬
- **?닿껐梨?*: `navigateToUrl()` ?⑥닔 ?댁뿉??pathname??諛붾??뚭퉴吏
  `waitFor(pathname change, 3000ms)` ?湲곕? 異붽?
  ```javascript
  async function navigateToUrl(url) {
    var beforePath = global.location.pathname;
    global.location.href = url;
    try {
      await waitFor(function() {
        return global.location.pathname !== beforePath;
      }, 3000, 100);
    } catch (e) {}
    return { action: "navigateToUrl", url: url };
  }
  ```

### 3-3. 諛⑸Ц 肄붾뱶 留ㅽ븨
```
100 ??SCR (Screening)
110 ??V1, 120 ??V2, 130 ??V3, 140 ??V4, 150 ??V5
160 ??V6, 170 ??V7, 180 ??V8, 190 ??V9
2001 ??UV1
```
- `planner.py`??`_VISIT_CODE_TO_SEGMENT` dict
- `DVSRunner(visit_map={...})` 濡??ㅽ꽣?붾퀎 ?ㅻ쾭?쇱씠??媛??
---

## 4. Python ?대씪?댁뼵??(`src/cdm_agent_client/`)

### 4-1. ?뚯씪 援ъ“
```
src/cdm_agent_client/
?쒋?? __init__.py          # CDMSAgent, DVSRunner lazy export
?쒋?? client.py            # CDMSAgent ??HTTP ?섑띁 (硫붿씤 ?대씪?댁뼵??
?쒋?? models.py            # PageSnapshot, StepResult, PageList dataclasses
?쒋?? exceptions.py        # CDMAgentError, StepFailedError, DaemonNotRunningError ...
?붴?? dvs/
    ?쒋?? __init__.py      # DVSRunner, DVSResult, DVSRow, Precondition export
    ?쒋?? schema.py        # 紐⑤뱺 dataclass ?뺤쓽
    ?쒋?? registry.py      # ItemRegistry ??Excel?먯꽌 ItemID/Label ??ItemDef 留ㅽ븨 鍮뚮뱶
    ?쒋?? parser.py        # Test Script ?뚯떛 + Excel ???뚯떛
    ?쒋?? planner.py       # Precondition 由ъ뒪????ActionStep 由ъ뒪??(navigate/set/save)
    ?쒋?? checker.py       # Expected Result ??PASS/FAIL ?먯젙 (has_query 湲곕컲)
    ?쒋?? reporter.py      # write_excel() + write_html() 寃곌낵 湲곕줉
    ?붴?? runner.py        # DVSRunner ???ㅼ??ㅽ듃?덉씠??```

### 4-2. CDMSAgent 二쇱슂 硫붿꽌??
```python
agent = CDMSAgent(study_id="FAST_AF")  # base_url 湲곕낯媛? http://127.0.0.1:3100

agent.inspect()          # ??PageSnapshot (visibleRows, invalidRowLabels, pathname ??
agent.go_to_page("V1/SV")   # 諛⑸Ц+?섏씠吏 ?대룞. "SV"硫??섏씠吏留? "V2/SV/2"硫??몄뒪?댁뒪源뚯?
agent.navigate_to("/path")  # ?덈? pathname ?대룞
agent.set_date("Visit date", "2024-01-01")   # ?좎쭨 ?щ젰 ?앹뾽 泥섎━
agent.set_text("Height", "170")              # ?쇰컲 ?띿뒪??agent.select_radio("Smoking", "Current smoker")  # ?쇰뵒?ㅻ쾭??(CDP ?꾩슂)
agent.click_save()       # Save 踰꾪듉
agent.click_save_next()  # Save & Next 踰꾪듉
agent.has_query()        # ??bool (Query 諛쒖깮 ?щ?)
agent.check_result("Query")  # ??"PASS" or "FAIL"
agent.list_pages()       # ?ъ씠?쒕컮 CRF ?섏씠吏 紐⑸줉
agent.ping()             # ?곕が ?앹〈 ?뺤씤

agent.raise_on_failure = False  # StepFailedError ?듭젣
```

### 4-3. PageSnapshot 二쇱슂 ?꾨뱶
```python
snap.connected          # bool
snap.pathname           # ?꾩옱 URL pathname (go_to_page?먯꽌 ?ъ슜)
snap.page_label         # ?섏씠吏紐?snap.invalid_row_labels # Query 諛쒖깮???꾨뱶紐?由ъ뒪??snap.invalid_count      # Query 媛쒖닔
snap.visible_rows       # 蹂댁씠?????쇰꺼 由ъ뒪??snap.enabled_actions    # ?쒖꽦?붾맂 ?≪뀡 由ъ뒪??(Phase 2?먯꽌 ?ъ슜)
```

---

## 5. DVS ?먮룞??紐⑤뱢 (`dvs/`)

### 5-1. DVS Excel 援ъ“
| ??| ?댁슜 | ?덉떆 |
|---|---|---|
| A | DVS ID | D_EN_SQ_1 |
| B | Domain | EN |
| C | Page Label | Registration |
| D | Visit Code | 100, 110 |
| E | Item ID | RFICDTC |
| F | Item Label | ?숈쓽 痍⑤뱷??|
| H | Layout | TEXT, DATE, RADIO, SINGLE_SELECT |
| I | Data Type | NVARCHAR(20), DATE |
| J | DVS Type | ?쒖뒪?? ?쒖꽦?? ?먮룞?곗궛 |
| K | Specification | RFICDTC < IRB Approval Date |
| L | Query Message | [?숈쓽 痍⑤뱷?? ?낅젰 ?꾨씫 |
| M | No | 1 |
| N | Test Script | RFICDTC=2023-12-31 |
| O | Expected Result | Query / No Query |
| R | Result (湲곕줉) | PASS/FAIL 湲곕줉 ?????|
| S | Comment (湲곕줉) | 鍮꾧퀬 湲곕줉 ?????|

?곗씠?곕뒗 4?됰????쒖옉. 3?됱씠 ?ㅻ뜑.

### 5-2. Test Script 臾몃쾿
```
RFICDTC=2024-01-01          ??item_key="RFICDTC", value="2024-01-01"
[V2]SVDTC=2024-01-05        ??visit_qualifier="V2", item_key="SVDTC"
EN.RFICDTC=2024-01-01       ??domain_qualifier="EN", item_key="RFICDTC"
SVDTC=null                  ??value=None  (?꾨뱶 ?대━??
IRB Approval Date=2024-01-01 ??ItemRegistry???놁쑝硫?external_context濡?遺꾨쪟
```

### 5-3. DVS Type ?꾪솴 (FAST-AF 湲곗?)
| Type | 嫄댁닔 | Expected | ?먮룞???④퀎 |
|---|---|---|---|
| ?쒖뒪??| 381 | Query / No Query | **Phase 1 ?꾩꽦** |
| ?쒖꽦??| 351 | ?쒖꽦??/ 鍮꾪솢?깊솕 | Phase 2 (誘멸뎄?? |
| ?먮룞?곗궛 | 101 | 怨꾩궛媛?| Phase 3 |
| 遺遺꾪솢?깊솕 | 32 | ?쒖꽦??/ 鍮꾪솢?깊솕 | Phase 2 |
| 遺덇???| 7 | ??| ?섎룞 |

### 5-4. DVSRunner ?ъ슜踰?(Jupyter)

```python
from cdm_agent_client import CDMSAgent
from cdm_agent_client.dvs import DVSRunner

agent = CDMSAgent(study_id="FAST_AF")
runner = DVSRunner(
    agent,
    "FAST-AF_EDC Validation List_001_draft.xlsx",
    visit_map={"100": "SCR"},   # ?ㅽ꽣?붾퀎 諛⑸Ц肄붾뱶 ?ㅻ쾭?쇱씠??)

# ?? ?명듃遺??앹꽦 (硫붿씤 ?뚰겕?뚮줈?? ??????????????????????????
# ? ?섎굹???쒕굹由ъ삤 ?섎굹. ?섎룞 寃??媛??
runner.generate_notebook("dvs_review.ipynb", dvs_type="?쒖뒪??)
# ???앹꽦??.ipynb瑜?Jupyter?먯꽌 ?댁뼱 ? ?섎굹???ㅽ뻾

# ?명듃遺??댁뿉??寃곌낵瑜??섎룞?쇰줈 湲곕줉????
runner.record("D_EN_SQ_1", 1, "PASS")
runner.record("D_EN_SQ_2", 1, "FAIL", "荑쇰━ 誘몃컻???뺤씤")

# 紐⑤뱺 寃곌낵瑜?*_validated.xlsx ?????
runner.flush_to_excel()

# ?? ?붾쾭源낆슜: ?뚯떛 寃곌낵留??뺤씤 (釉뚮씪?곗? 誘몄젒珥? ??????????
runner.dry_run(dvs_type="?쒖뒪??)   # ??pandas DataFrame

# ?? ?꾩쟾 ?먮룞 ?ㅽ뻾 (?덇굅??紐⑤뱶) ?????????????????????????
runner.run_all(dvs_type="?쒖뒪??)   # ??list[DVSResult] + ?묒?+HTML ?먮룞 ???runner.run_one("D_EN_SQ_1")
runner.run_one("D_EN_SQ_1", no=2)
```

### 5-5. generate_notebook() ?앹꽦 ? 援ъ“
```python
# ?? D_EN_SQ_1  No=1  ????????????????????????????
# Page     : Registration  |  DVS Type: ?쒖뒪??# Spec     : RFICDTC < IRB Approval Date ?대㈃ Query
# Query    : [?숈쓽 痍⑤뱷?? ?낅젰 ?꾨씫
# Expected : Query
# [?몃?媛?  IRB Approval Date='2024-01-01'

agent.raise_on_failure = False
agent.go_to_page("SCR/EN")
agent.raise_on_failure = True
agent.set_date("?숈쓽 痍⑤뱷??, "2023-12-31")
agent.click_save()

print(runner._check("D_EN_SQ_1", 1, "Query", "[?숈쓽 痍⑤뱷?? ?낅젰 ?꾨씫"))
# 寃곌낵 ?섎룞 蹂寃? runner.record("D_EN_SQ_1", 1, "PASS"/"FAIL")
```

---

## 6. checker.py ??寃곌낵 ?먯젙 濡쒖쭅

```python
# evaluate(expected, agent, query_message) ??("PASS"|"FAIL"|"SKIP", detail)

"Query" / "q"           ??agent.inspect().invalid_count > 0 ?대㈃ PASS
"No Query" / "nq"       ??invalid_count == 0 ?대㈃ PASS
"?쒖꽦??, "鍮꾪솢?깊솕"     ??SKIP (Phase 2 誘멸뎄??
怨꾩궛媛???              ??SKIP (Phase 3 誘멸뎄??
```

---

## 7. Chrome Extension (`extension/`)

| ?뚯씪 | ??븷 |
|---|---|
| `browser-runner-core.js` | DOM 議곗옉 ?듭떖 濡쒖쭅 (CDMS ??뿉???ㅽ뻾) |
| `content-script.js` | ????service-worker 硫붿떆吏 以묎퀎 |
| `service-worker.js` | ?곕が WebSocket ????議곗쑉, CDP 沅뚰븳 愿由?|
| `sidepanel.js` | ?ъ씠?쒗뙣??UI |

### Extension 二쇱슂 runner ?⑥닔 (browser-runner-core.js)
- `setDateViaCalendarPopup(rowLabel, value)` ???좎쭨 ?낅젰
- `setText(rowLabel, value)` ???띿뒪???낅젰
- `selectRadio(rowLabel, optionLabel)` ??**CDP ?꾩닔** (isTrusted 臾몄젣)
- `clickSave()` ?????- `navigateToUrl(url)` ??SPA ?대룞 (waitFor pathname ?ы븿)
- `inspectActivePage()` ???ㅻ깄??諛섑솚

---

## 8. ?ㅼ쓬 ?묒뾽 ?④퀎

### Phase 2: ?쒖꽦??鍮꾪솢?깊솕 ?먯젙
1. `browser-runner-core.js`??`isFieldEnabled(rowLabel)` ?⑥닔 異붽?
   - `aria-disabled="true"` ?먮뒗 `input.disabled` 泥댄겕
   - `inspectActivePage()` ?묐떟??`enabledFields` 諛곗뿴 異붽?
2. `checker.py`??`evaluate()` ??`"?쒖꽦??` / `"鍮꾪솢?깊솕"` 耳?댁뒪 援ы쁽
   ```python
   if norm in ("?쒖꽦??, "enabled"):
       snap = agent.inspect()
       # snap.enabled_actions ?먮뒗 ??enabledFields ?ъ슜
   ```
3. `DVSRunner.run_all(dvs_type="?쒖꽦??)` ?뚯뒪??
### 湲고? ?붿뿬 ?묒뾽
- Extension ?щ줈???꾩슂 (?좏깮??蹂寃? navigateToUrl ?섏젙??釉뚮씪?곗???誘몃컲???곹깭?????덉쓬)
- `runner.generate_notebook()` ?ㅼ젣 Excel濡??ㅻえ???뚯뒪??- `flush_to_excel()` ??R/S ??踰덊샇 ?뺤씤 (?꾩옱 R=18, S=19 怨좎젙 ???ㅽ꽣?붾퀎 ?ㅻ? ???덉쓬)

---

## 9. 媛쒕컻 ?섍꼍 / ?ㅼ튂

```bash
cd C:\Users\SunbeomGwon\CDMS-Agent
pip install -e ".[dvs,dev]"   # openpyxl ?ы븿

# Chrome Extension 濡쒕뱶: chrome://extensions ???뺤텞 ?댁젣???뺤옣 ?꾨줈洹몃옩 濡쒕뱶 ??extension/
# Daemon: Next.js ??蹂꾨룄 ?ㅽ뻾 (?ы듃 3100)
```

### ?섏〈??- Python >= 3.9
- `requests>=2.28` (?꾩닔)
- `openpyxl>=3.1` (dvs 湲곕뒫??
- `pandas`, `ipython`, `notebook` (?좏깮)
