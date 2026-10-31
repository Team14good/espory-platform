# 模組介面約定

CONTRIBUTING 6.5：各模組負責人寫下別人會呼叫的 `service.py` 公開函式，下游照約定先寫，不必等上游合併。

| 模組 | 負責人 | 約定 |
| --- | --- | --- |
| competition | D 黃鉅燊 | [competition.md](competition.md) |
| tournaments | B 蘇采羚 | [tournaments.md](tournaments.md) |
| registration | C 邱芯彤 | 待補；competition 需要的部分先列在 competition.md〈二〉 |
| identity、notifications | A 王閎立 | 待補 |

規則：

- 函式風格沿用既有程式：模組層級函式、第一個參數是 `session`、其餘用關鍵字參數；service 不 commit（AD-5）。
- 名稱與參數有異議，直接在該檔的 PR 留言，或開 PR 修改；合併後以這份為準，實作時如果需要改，先改這份。
- 上游還沒實作時，下游用測試替身（monkeypatch 對方的 service 函式）先寫，接上真實函式後刪掉替身。
