"""入力の大きさの上限（決まり SEC-04）。

`/api/verify`・`/api/records` は、画面が送り返す下書きと発言の列をそのまま受ける。
上限がないと、`evidence` を数万件並べた下書きで二段目の入力作りがメモリを使い切る。
上限を超えた入力は、形の誤り（422）として受け付けない。
"""

from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

MAX_TEXT_CHARS = 5000  # 1つの文・発言の文字数
MAX_EVIDENCE = 3  # 1つの要素の根拠の発言（重複を除いた数）
MAX_UTTERANCES = 200  # 発言の列
MAX_SENTENCES = 50  # S・O それぞれの文の数
MAX_ITEMS = 30  # バイタル・依頼・手で入力が必要なもの・医師への確認、それぞれの数
MAX_DECISIONS = 300  # 残す／消す・二段目の判定の数（どちらも要素の数より多くは要らない）
MAX_ID_CHARS = 40
# 記録・タスクに残す発言の文の長さと、タスクに残す「患者の発言そのまま」の数（P-02）
MAX_SAVED_CHARS = 1000
MAX_PATIENT_WORDS = 3

ID_PATTERN = rf"^[A-Za-z0-9_-]{{1,{MAX_ID_CHARS}}}$"

# 患者・タスク・確定の id（Firestore の文書の id にも使う）
SafeId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
# 発言番号。Gemini が返した番号も入るので、形は問わず長さだけを限る（存在しない番号は照合で止める）
UtteranceId = Annotated[str, StringConstraints(max_length=MAX_ID_CHARS)]
Text = Annotated[str, StringConstraints(max_length=MAX_TEXT_CHARS)]
ShortText = Annotated[str, StringConstraints(max_length=100)]


def unique_evidence(ids: list[str]) -> list[str]:
    """重複を除き、上限の件数以内かを確かめる。

    Raises:
        ValueError: 重複を除いても MAX_EVIDENCE 件を超える場合
    """
    unique = list(dict.fromkeys(ids))
    if len(unique) > MAX_EVIDENCE:
        raise ValueError(f"根拠の発言は{MAX_EVIDENCE}件までです（{len(unique)}件）")
    return unique


# 重複を除く前の並びも、ばかげた長さは受けない
Evidence = Annotated[
    list[UtteranceId], Field(max_length=MAX_EVIDENCE * 5), AfterValidator(unique_evidence)
]
