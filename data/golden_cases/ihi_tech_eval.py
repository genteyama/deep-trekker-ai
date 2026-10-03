from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Optional

from data.golden_cases.loader import IHI_TECH_001, load_golden_case, load_manufacturer_response_golden_case
from models import QuestionStatus, QuestionTarget, TechnicalQuestion

MATCH = "MATCH"
PARTIAL = "PARTIAL"
MISSING = "MISSING"
UNSUPPORTED = "UNSUPPORTED"
THINKING_KEYS = {"thinking", "reasoning", "thought", "reasoning_content", "thinking_process"}
THINKING_MARKERS = ("Thinking...", "Thinking Process", "<think>", "</think>")
HALLUCINATION_MARKERS = (
    "ATEX",
    "IECEx",
    "防爆認証",
    "防爆規格",
    "explosion-proof",
    "IP68",
    "IP67",
    "50 lb",
    "50lb",
    "45kgf",
    "45 kgf",
    "2604",
    "2601",
)
PRICE_FACT_RE = re.compile(r"(\$|USD|万円)\s*\d+|\d[\d,]*\s*(\$|USD|万円)")
LEAD_TIME_FACT_RE = re.compile(r"納期.{0,12}\d.{0,8}(週|日|か月|ヶ月|営業日)")
GPS_REINTERPRET_RE = re.compile(r"GPSが(ない|無い|ありません)")
ANSWER_TOPIC_KEYWORDS = {
    "cygnus_body_shareable": ["本体", "共有", "付け替え", "共用"],
    "integration_kit_required_per_vehicle": ["Integration Kit", "インテグレーション", "機体ごと", "機種別"],
    "manufacturer_recommends_rov_plus_gauge": ["ROV", "超音波"],
    "photon_plus_cygnus_proposed": ["PHOTON", "Cygnus"],
    "mag_cannot_transition_surfaces": ["面", "移動"],
    "mag_no_structure_self_position": ["自己位置", "水深", "テザー"],
}


@dataclass
class TopicScore:
    topic_id: str
    classification: str
    hits: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Finding:
    classification: str
    item_id: str
    detail: str
    area: str


@dataclass
class EvaluationReport:
    case_id: str
    stage: str
    scores: list[TopicScore]
    findings: list[Finding]
    thinking_leaks: list[str]
    usage: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "stage": self.stage,
            "scores": [asdict(item) for item in self.scores],
            "findings": [asdict(item) for item in self.findings],
            "thinking_leaks": list(self.thinking_leaks),
            "usage": self.usage,
            "counts": counts_by_class(self.scores, self.findings),
        }


def counts_by_class(scores: list[TopicScore], findings: list[Finding]) -> dict:
    counts = {MATCH: 0, PARTIAL: 0, MISSING: 0, UNSUPPORTED: 0}
    for item in scores:
        counts[item.classification] += 1
    for item in findings:
        counts[item.classification] += 1
    return counts


def load_ihi_tech_fixtures() -> dict:
    initial = load_golden_case(IHI_TECH_001)
    response = load_manufacturer_response_golden_case()
    return {
        "input": initial["input"],
        "expected": initial["expected"],
        "response_expected": response["expected"],
        "source_notes": response["source_notes"],
    }


def flatten_strings(value: Any) -> str:
    chunks = []
    _collect_strings(value, chunks)
    return "\n".join(chunks)


def _collect_strings(value: Any, chunks: list[str]) -> None:
    if isinstance(value, str):
        chunks.append(value)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_strings(item, chunks)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_strings(item, chunks)


def contains_alias(text: str, alias: str) -> bool:
    if not text or not alias:
        return False
    return alias.casefold() in text.casefold()


def alias_hits(text: str, aliases: list[str]) -> list[str]:
    return [alias for alias in aliases if contains_alias(text, alias)]


def find_thinking_leaks(payload: Any, path: str = "$") -> list[str]:
    leaks = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            current = f"{path}.{key}"
            if str(key).casefold() in THINKING_KEYS:
                leaks.append(current)
            leaks.extend(find_thinking_leaks(value, current))
        return leaks
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            leaks.extend(find_thinking_leaks(value, f"{path}[{index}]"))
        return leaks
    if isinstance(payload, str):
        for marker in THINKING_MARKERS:
            if marker in payload:
                leaks.append(f"{path}:{marker}")
    return leaks


def analysis_fact_text(payload: dict) -> str:
    parts = [payload.get("case_summary") or ""]
    for item in payload.get("requirements") or []:
        parts.extend([item.get("label") or "", item.get("value") or "", item.get("notes") or ""])
    for item in payload.get("unresolved_items") or []:
        parts.extend([item.get("label") or "", item.get("notes") or ""])
    parts.extend(payload.get("requested_products") or [])
    return "\n".join(parts)


def analysis_question_text(payload: dict, *keys: str) -> str:
    chunks = []
    for key in keys:
        for item in payload.get(key) or []:
            chunks.append(item.get("question") or "")
    return "\n".join(chunks)


def classify_topic(text: str, topic: dict) -> TopicScore:
    hits = alias_hits(text, topic.get("aliases") or [])
    stated = topic.get("stated_value")
    stated_hit = bool(stated) and contains_alias(text, stated)
    if stated:
        if stated_hit and hits:
            return TopicScore(topic["topic_id"], MATCH, hits, "値とテーマの両方がある")
        if stated_hit or hits:
            return TopicScore(topic["topic_id"], PARTIAL, hits, "テーマまたは値のどちらかだけ")
        return TopicScore(topic["topic_id"], MISSING, [], "抽出なし")
    if hits:
        return TopicScore(topic["topic_id"], MATCH, hits)
    return TopicScore(topic["topic_id"], MISSING, [], "抽出なし")


def evaluate_initial_analysis(payload: dict, expected: dict, usage: Optional[dict] = None) -> EvaluationReport:
    requirement_text = analysis_fact_text(payload)
    manufacturer_text = analysis_question_text(payload, "manufacturer_questions", "technical_questions")
    customer_text = analysis_question_text(payload, "customer_questions")
    all_text = flatten_strings(payload)
    scores = []
    for topic in expected["required_requirement_topics"]:
        scores.append(classify_topic(requirement_text + "\n" + all_text, topic))
    for topic in expected["required_manufacturer_question_topics"]:
        score = classify_topic(manufacturer_text, topic)
        if score.classification == MISSING:
            customer_hits = alias_hits(customer_text, topic.get("aliases") or [])
            if customer_hits:
                score = TopicScore(topic["topic_id"], PARTIAL, customer_hits, "顧客確認側にのみ出現")
        scores.append(score)

    findings = []
    findings.extend(_requested_product_findings(payload, expected))
    findings.extend(_initial_unsupported_findings(payload, expected, all_text, requirement_text))
    thinking_leaks = find_thinking_leaks(payload)
    for leak in thinking_leaks:
        findings.append(Finding(UNSUPPORTED, "thinking_leak", leak, "thinking"))

    return EvaluationReport(
        case_id=expected["case_id"],
        stage="INITIAL_CUSTOMER_INQUIRY",
        scores=scores,
        findings=findings,
        thinking_leaks=thinking_leaks,
        usage=usage,
    )


def _requested_product_findings(payload: dict, expected: dict) -> list[Finding]:
    findings = []
    products = " ".join(payload.get("requested_products") or [])
    summary = payload.get("case_summary") or ""
    if not contains_alias(products + summary, expected["requested_product"]):
        findings.append(Finding(MISSING, "requested_product", "顧客指定製品MAGが抽出されていない", "candidates"))
    if contains_alias(summary, "最適") and contains_alias(summary, "MAG"):
        findings.append(Finding(UNSUPPORTED, "mag_is_optimal_product", "MAGを最適製品として断定している", "candidates"))
    if contains_alias(summary, "スペースワン推奨") or contains_alias(summary, "SpaceOne推奨"):
        findings.append(Finding(UNSUPPORTED, "mag_is_spaceone_recommended", "顧客指定を推奨扱いしている", "candidates"))
    return findings


def _initial_unsupported_findings(payload: dict, expected: dict, all_text: str, fact_text: str) -> list[Finding]:
    findings = []
    for fact in expected.get("later_facts_must_not_appear_in_input") or []:
        if contains_alias(fact_text, fact):
            findings.append(Finding(UNSUPPORTED, "later_fact", f"初期段階に後出し事実がある: {fact}", "hallucination"))
    for marker in HALLUCINATION_MARKERS:
        if contains_alias(fact_text, marker):
            findings.append(Finding(UNSUPPORTED, "hallucination_marker", f"入力にない内容を生成: {marker}", "hallucination"))
    if PRICE_FACT_RE.search(fact_text):
        findings.append(Finding(UNSUPPORTED, "price_generated", "価格数値を生成している", "hallucination"))
    if LEAD_TIME_FACT_RE.search(fact_text):
        findings.append(Finding(UNSUPPORTED, "specific_lead_time_generated", "具体納期を生成している", "hallucination"))
    assertion_map = {
        "mag_90_degree_transition_possible": ("90度移動できる", "面移動が可能", "底面へ移動できる"),
        "mag_90_degree_transition_impossible": ("90度移動できない", "面移動ができない", "底面へ移動できない"),
        "depth_sensor_exists": ("水深センサーがある", "水深計がある"),
        "depth_sensor_absent": ("水深センサーがない", "水深計がない"),
        "absolute_position_exists": ("絶対位置がある", "絶対位置を把握できる"),
        "absolute_position_absent": ("絶対位置がない", "絶対位置機能がない"),
        "tether_counter_exists": ("繰出長カウンターがある", "テザー長を把握できる"),
        "tether_counter_absent": ("繰出長カウンターがない", "テザー長が分からない"),
        "cygnus_ept_simultaneous_capability_asserted": ("同時搭載できる", "同時搭載できない"),
        "photon_is_officially_recommended": ("PHOTONを推奨", "PHOTONが最適", "PHOTONを正式"),
    }
    for assertion_id, aliases in assertion_map.items():
        if alias_hits(fact_text, list(aliases)):
            findings.append(Finding(UNSUPPORTED, assertion_id, "確認前に仕様を断定している", "hallucination"))
    return findings


def manufacturer_questions_from_golden() -> list[TechnicalQuestion]:
    fixtures = load_ihi_tech_fixtures()
    aliases_by_id = {
        item["topic_id"]: item["aliases"]
        for item in fixtures["expected"]["required_manufacturer_question_topics"]
    }
    questions = []
    for item in fixtures["response_expected"]["question_expectations"]:
        topic_id = item["question_topic"]
        aliases = aliases_by_id.get(topic_id) or [topic_id]
        questions.append(
            TechnicalQuestion(
                question_id=topic_id,
                case_id=fixtures["input"]["case_id"],
                target=QuestionTarget.MANUFACTURER,
                question="メーカー確認: " + " / ".join(aliases),
                status=QuestionStatus.DRAFT,
                follow_up_required=False,
            )
        )
    return questions


def manufacturer_response_fixture_text() -> str:
    notes = load_ihi_tech_fixtures()["source_notes"]
    lines = [
        "source_type=HUMAN_VERIFIED_MANUFACTURER_RESPONSE_SUMMARY",
        "raw_response_available=false",
        "This is a human-verified manufacturer confirmation summary. It is not a raw email.",
    ]
    for item in notes["verified_statements"]:
        lines.append(item["summary"])
    return "\n".join(lines)


def evaluate_manufacturer_response(payload: dict, expected: dict, usage: Optional[dict] = None) -> EvaluationReport:
    matches = {item.get("question_id"): item for item in payload.get("matches") or []}
    all_text = flatten_strings(payload)
    scores = []
    findings = []
    answered = 0
    for item in expected["question_expectations"]:
        topic_id = item["question_topic"]
        match = matches.get(topic_id) or {}
        status = _status_value(match.get("suggested_status"))
        expected_status = item["expected_status"]
        score = _classify_status(topic_id, status, expected_status, item)
        scores.append(score)
        if status == "ANSWERED":
            answered += 1
        if expected_status == "FOLLOW_UP_REQUIRED" and status == "ANSWERED":
            findings.append(
                Finding(UNSUPPORTED, topic_id, "根拠不足の質問をANSWEREDにしている", "manufacturer_response")
            )
        answer_text = " ".join(
            [
                match.get("answer_summary") or "",
                match.get("evidence_text") or "",
                match.get("follow_up_question") or "",
            ]
        )
        for answer_topic in item.get("expected_answer_topics") or []:
            keywords = ANSWER_TOPIC_KEYWORDS.get(answer_topic) or []
            if status in {"ANSWERED", "PARTIAL"} and keywords and not alias_hits(all_text + answer_text, keywords):
                scores.append(
                    TopicScore(answer_topic, PARTIAL, [], f"{topic_id} の回答要素が不足")
                )
    if answered == len(expected["question_expectations"]):
        findings.append(Finding(UNSUPPORTED, "all_answered", "全質問をANSWEREDにしている", "manufacturer_response"))

    findings.extend(_manufacturer_unsupported_findings(payload, expected, all_text))
    thinking_leaks = find_thinking_leaks(payload)
    for leak in thinking_leaks:
        findings.append(Finding(UNSUPPORTED, "thinking_leak", leak, "thinking"))

    for topic in expected.get("expected_unmatched_information") or []:
        unmatched_text = flatten_strings(payload.get("unmatched_information") or [])
        hits = alias_hits(unmatched_text + all_text, topic.get("aliases") or [])
        if hits:
            scores.append(TopicScore(topic["topic_id"], MATCH, hits, "追加情報として捕捉"))
        else:
            scores.append(TopicScore(topic["topic_id"], MISSING, [], "質問外の追加情報を抽出できていない"))

    return EvaluationReport(
        case_id=expected["case_id"],
        stage="AFTER_MANUFACTURER_RESPONSE",
        scores=scores,
        findings=findings,
        thinking_leaks=thinking_leaks,
        usage=usage,
    )


def _status_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return getattr(value, "value", value)


def _classify_status(topic_id: str, actual: Optional[str], expected_status: str, item: dict) -> TopicScore:
    if actual is None:
        return TopicScore(topic_id, MISSING, [], "照合結果なし")
    if actual == expected_status:
        return TopicScore(topic_id, MATCH, [actual], item.get("notes") or "")
    if {actual, expected_status} <= {"ANSWERED", "PARTIAL"}:
        return TopicScore(topic_id, PARTIAL, [actual], f"期待 {expected_status} / 実際 {actual}")
    if actual == "PARTIAL" and expected_status == "FOLLOW_UP_REQUIRED":
        return TopicScore(topic_id, PARTIAL, [actual], "未完了方向は合っている")
    if actual == "FOLLOW_UP_REQUIRED" and expected_status == "PARTIAL":
        return TopicScore(topic_id, PARTIAL, [actual], "追加確認は残している")
    if actual == "FOLLOW_UP_REQUIRED" and expected_status == "ANSWERED":
        return TopicScore(topic_id, MISSING, [actual], "確認済み事実を拾えていない")
    return TopicScore(topic_id, UNSUPPORTED, [actual], f"期待 {expected_status} / 実際 {actual}")


def _manufacturer_unsupported_findings(payload: dict, expected: dict, all_text: str) -> list[Finding]:
    findings = []
    if contains_alias(all_text, "AI_SUGGESTED") and contains_alias(all_text, "PHOTON"):
        findings.append(Finding(UNSUPPORTED, "photon_ai_suggested", "PHOTONをAI提案として扱っている", "origins"))
    if contains_alias(all_text, "45kgf") or contains_alias(all_text, "45 kgf"):
        findings.append(Finding(UNSUPPORTED, "45kgf_guarantee", "SpaceOne参考値をメーカー保証のように扱っている", "hallucination"))
    if GPS_REINTERPRET_RE.search(all_text):
        findings.append(Finding(UNSUPPORTED, "gps_reinterpret", "自己位置の説明をGPSがないへ変換している", "hallucination"))
    if PRICE_FACT_RE.search(all_text):
        findings.append(Finding(UNSUPPORTED, "price_generated", "価格数値を生成している", "hallucination"))
    if LEAD_TIME_FACT_RE.search(all_text):
        findings.append(Finding(UNSUPPORTED, "specific_lead_time_generated", "具体納期を生成している", "hallucination"))
    for marker in ("ATEX", "IECEx", "防爆認証", "2604", "2601"):
        if contains_alias(all_text, marker):
            findings.append(Finding(UNSUPPORTED, "hallucination_marker", f"fixtureにない内容を生成: {marker}", "hallucination"))
    return findings


def usage_dict(record) -> Optional[dict]:
    if record is None:
        return None
    return {
        "provider": record.provider,
        "model": record.model,
        "duration_ms": record.duration_ms,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "success": record.success,
        "http_status": record.http_status,
        "operation": record.operation,
    }
