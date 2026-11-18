from __future__ import annotations

from collections import defaultdict
import logging
from typing import Any, Dict, List, Optional

from backend.app.config import get_settings
from backend.app.models import ChatMessage, FinancialRequest
from backend.app.services.api_clients import convert_currency, fetch_geolocation_context

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:  # pragma: no cover - optional dependency
    ChatGoogleGenerativeAI = None

try:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnableLambda
except Exception:  # pragma: no cover - optional dependency
    StrOutputParser = None
    ChatPromptTemplate = None
    RunnableLambda = None

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover - optional dependency
    Langfuse = None

logger = logging.getLogger(__name__)


def _match_category(description: str) -> str:
    text = description.lower()
    keyword_map = {
        "housing": ["rent", "mortgage", "apartment", "lease", "utilities", "electric", "water"],
        "loan": ["loan", "debt", "installment", "repayment"],
        "food": ["grocery", "restaurant", "coffee", "food", "cafe", "dinner", "lunch"],
        "transport": ["uber", "lyft", "fuel", "gas", "metro", "train", "bus", "parking"],
        "shopping": ["amazon", "market", "shopping", "clothes", "retail", "store"],
        "entertainment": ["movie", "netflix", "spotify", "games", "concert", "theater", "streaming"],
        "travel": ["flight", "hotel", "travel", "airbnb", "trip", "holiday"],
        "health": ["pharmacy", "medical", "clinic", "health", "gym"],
        "investment": ["investment", "stocks", "mutual fund", "sip", "equity", "shares", "etf", "bond", "brokerage"],
    }
    for category, keywords in keyword_map.items():
        if any(keyword in text for keyword in keywords):
            return category.title()
    return "Other"


class FinanceAgent:
    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def _session_key(self, session_id: Optional[str]) -> str:
        return session_id or "default-session"

    def _get_session(self, session_id: Optional[str]) -> Dict[str, Any]:
        session_key = self._session_key(session_id)
        if session_key not in self.sessions:
            self.sessions[session_key] = {
                "income": 0.0,
                "currency": "USD",
                "transactions": [],
                "goals": [],
                "preferences": {},
                "chat_history": [],
            }
        return self.sessions[session_key]

    def _apply_session_updates(self, session: Dict[str, Any], payload: Dict[str, Any]) -> None:
        if payload.get("income") is not None:
            session["income"] = float(payload["income"])
        if payload.get("currency"):
            session["currency"] = payload["currency"].upper()
        if payload.get("transactions"):
            session["transactions"].extend(payload["transactions"])
        if payload.get("goals"):
            session["goals"] = payload["goals"]

    def _convert_amount(self, amount: float, source_currency: str, target_currency: str) -> float:
        if source_currency == target_currency:
            return amount
        return convert_currency(amount, source_currency, target_currency)

    def _build_analysis(self, session: Dict[str, Any], request: FinancialRequest) -> Dict[str, Any]:
        target_currency = (request.currency or session.get("currency") or "USD").upper()
        income = float(request.income if request.income else session.get("income", 0.0))
        expenses = []
        for txn in request.transactions:
            converted = self._convert_amount(txn.amount, txn.currency.upper(), target_currency)
            category = txn.category or _match_category(txn.description)
            cat = category.title()
            expenses.append({
                "description": txn.description,
                "amount": converted,
                "currency": target_currency,
                "category": cat,
                "date": txn.date,
            })

        category_totals: Dict[str, float] = defaultdict(float)
        for item in expenses:
            category_totals[item["category"]] += item["amount"]

        total_spending = round(sum(item["amount"] for item in expenses), 2)
        remaining = round(income - total_spending, 2)
        savings_rate = round((income - total_spending) / income * 100, 2) if income else 0.0
        top_category = max(category_totals.items(), key=lambda item: item[1], default=("Other", 0.0))

        monthly_budget = {
            "Housing": round(income * 0.30, 2),
            "Food": round(income * 0.18, 2),
            "Transport": round(income * 0.12, 2),
            "Shopping": round(income * 0.10, 2),
            "Entertainment": round(income * 0.08, 2),
            "Savings": round(income * 0.20, 2),
            "Other": round(income * 0.02, 2),
        }

        alerts: List[str] = []
        for category, total in category_totals.items():
            if category in monthly_budget and total > monthly_budget[category]:
                alerts.append(f"{category} is above its recommended monthly budget by {round(total - monthly_budget[category], 2)} {target_currency}.")

        if income > 0 and savings_rate < 10:
            alerts.append("Savings rate is below a healthy target of 10% to 20% of income.")

        goals = []
        if request.goal_name:
            goal_amount = float(request.goal_amount or 0)
            goal_saved = float(request.goal_saved or 0)
            progress = round((goal_saved / goal_amount) * 100, 2) if goal_amount else 0.0
            goals.append({
                "name": request.goal_name,
                "target": goal_amount,
                "saved": goal_saved,
                "progress": progress,
                "remaining": round(max(goal_amount - goal_saved, 0), 2),
            })

        geo = fetch_geolocation_context(request.location)
        recommendations = [
            f"Keep at least 20% of income for savings and emergency reserves.",
            f"Your heaviest spending area is {top_category[0]} with {top_category[1]:,.2f} {target_currency}.",
            "Review recurring subscriptions and informal daily spending to improve cash flow.",
        ]
        if geo.get("country"):
            recommendations.append(f"Regional context suggests your spending profile is associated with {geo.get('city') or geo.get('country')}. Consider local living-cost benchmarks.")

        return {
            "income": round(income, 2),
            "currency": target_currency,
            "total_spending": round(total_spending, 2),
            "remaining": round(remaining, 2),
            "savings_rate": round(savings_rate, 2),
            "largest_category": top_category[0],
            "largest_category_amount": round(top_category[1], 2),
            "categories": {k: round(v, 2) for k, v in sorted(category_totals.items())},
            "budget_recommendations": {k: round(v, 2) for k, v in monthly_budget.items()},
            "alerts": alerts,
            "recommendations": recommendations,
            "goals": goals,
            "location_context": geo,
            "transactions": expenses,
        }

    @staticmethod
    def _local_finance_reply(analysis: Dict[str, Any], reason: str) -> str:
        currency = analysis.get("currency", "USD")
        spending = float(analysis.get("total_spending", 0))
        remaining = float(analysis.get("remaining", 0))
        savings_rate = float(analysis.get("savings_rate", 0))
        categories: Dict[str, float] = analysis.get("categories") or {}
        top_category = max(categories, key=lambda category: categories[category]) if categories else None
        reply_lines = [
            reason,
            f"Spending: {spending:,.2f} {currency}.",
            f"Remaining: {remaining:,.2f} {currency}.",
            f"Savings rate: {savings_rate:.1f}%.",
        ]
        if top_category:
            reply_lines.append(f"Highest spending category: {top_category}.")
        recommendations = analysis.get("recommendations") or []
        if recommendations:
            reply_lines.append(f"Next step: {recommendations[min(1, len(recommendations) - 1)]}")
        return "\n".join(reply_lines)

    @staticmethod
    def _local_chat_reply(
        message: str,
        analysis: Dict[str, Any],
        location_context: Dict[str, Any],
        reason: str,
    ) -> str:
        question = message.casefold()
        words = {word.strip(".,!?;:") for word in question.split()}
        city = location_context.get("city")
        currency = analysis.get("currency", "USD")

        if words.intersection({"hello", "hi", "hey"}):
            return "Hello! I’m your Personal Finance & Budget Advisor. Ask me about your spending, savings, budget, or goals."

        if any(phrase in question for phrase in ("who are you", "what ai", "which ai", "which agent", "what agent")):
            return "I’m the Personal Finance & Budget Advisor. I can help review your budget, spending, savings, and goals."

        if any(phrase in question for phrase in ("current city", "what city", "which city", "where am i", "current location", "my location")):
            if city:
                return f"Location available in your finance profile: {city}."
            return "I don’t have a confirmed city yet. Allow location access in the dashboard or enter a city in the Location field, then ask again."

        if any(phrase in question for phrase in ("cost of living", "living cost", "living expenses")):
            if city:
                return (
                    f"Cost of living in {city} for two adults and two children:\n"
                    "I don’t have a live local-prices feed, so I can’t verify a current monthly total.\n"
                    "Include housing, groceries, utilities, transport, school or childcare, and healthcare in your estimate.\n"
                    f"Share your expected housing and school costs and I can build a practical budget in {currency}."
                )
            return "I need your city to make this location-specific. Allow location access or enter a city, then ask again."

        if any(word in question for word in ("saving", "savings", "save")):
            return (
                f"Savings rate: {float(analysis.get('savings_rate', 0)):.1f}%.\n"
                f"Amount remaining after listed expenses: {float(analysis.get('remaining', 0)):,.2f} {currency}."
            )

        if any(word in question for word in ("spending", "spent", "expense", "expenses", "category")):
            categories = analysis.get("categories") or {}
            top_category = max(categories, key=categories.get) if categories else None
            lines = [f"Total listed spending: {float(analysis.get('total_spending', 0)):,.2f} {currency}."]
            if top_category:
                lines.append(
                    f"Largest category: {top_category} at {float(categories[top_category]):,.2f} {currency}."
                )
            return "\n".join(lines)

        return (
            f"{reason}\n"
            "I can answer questions using the figures in your dashboard. Try asking about a specific expense, "
            "category, savings rate, or goal."
        )

    def _build_lcel_chain(self, system_message: str):
        settings = get_settings()
        if not settings.gemini_api_key:
            return None
        if ChatGoogleGenerativeAI is None:
            return None
        if ChatPromptTemplate is None or StrOutputParser is None or RunnableLambda is None:
            return None

        model_options = {
            "model": settings.gemini_model_name,
            "google_api_key": settings.gemini_api_key,
            "temperature": 0.2,
        }
        if settings.gemini_base_url:
            model_options["base_url"] = settings.gemini_base_url

        llm = ChatGoogleGenerativeAI(**model_options)

        def normalize_llm_output(messages):
            prompt_input = messages
            if hasattr(messages, "messages"):
                message_list = getattr(messages, "messages", [])
                if message_list:
                    prompt_input = message_list[-1].content
            elif isinstance(messages, dict):
                prompt_input = messages.get("input") or messages.get("text") or str(messages)
            response = llm.invoke(prompt_input)
            content = getattr(response, "content", response)
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                text_blocks = [
                    block if isinstance(block, str) else block.get("text", "")
                    for block in content
                    if isinstance(block, (str, dict))
                ]
                text = "\n".join(part for part in text_blocks if part).strip()
                if text:
                    return text
            return ""

        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("user", "{input}"),
        ])
        model = RunnableLambda(normalize_llm_output)
        return prompt_template | model | StrOutputParser()

    def _generate_ai_reply(
        self,
        prompt: str,
        analysis: Dict[str, Any],
        user_message: Optional[str] = None,
        location_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        settings = get_settings()
        def fallback_reply(reason: str) -> str:
            if user_message is None:
                return self._local_finance_reply(analysis, reason)
            return self._local_chat_reply(
                user_message,
                analysis,
                location_context or {},
                reason,
            )

        if not settings.gemini_api_key:
            return fallback_reply("Gemini is not configured because GEMINI_API_KEY is empty.")
        if ChatGoogleGenerativeAI is None:
            return fallback_reply("The LangChain Gemini integration is unavailable.")

        system_message = (
            "You are the Personal Finance & Budget Advisor. Answer the user's latest question "
            "directly before offering advice. Keep the answer relevant to that question; do not "
            "attach a generic spending/savings recap to greetings, identity questions, or location "
            "questions. Use prior turns to resolve follow-up questions. Format multi-part answers as "
            "separate, point-by-point lines, not a summary paragraph; use one useful point per line and "
            "no table. Do not cap the response at 4-5 lines; include as many points as needed to fully "
            "answer."
            "Mention financial figures only when they help answer the question, and do not repeat them "
            "from the prior reply unless needed. For cost-of-living questions, use the household size "
            "and available city; do not claim live prices or exact current costs without a live data "
            "source, and clearly label estimates. Use provided location context when relevant; it is "
            "geocoded place information only, not weather or live pricing data, and should not be "
            "quoted as a raw object."
        )

        chain = self._build_lcel_chain(system_message)
        if chain is None:
            return fallback_reply("The LCEL Gemini chain is unavailable.")

        try:
            response = chain.invoke(prompt)
            response_content = getattr(response, "content", response)
            if isinstance(response_content, str) and response_content.strip():
                return response_content.strip()
            if isinstance(response_content, list):
                text_blocks = [
                    block if isinstance(block, str) else block.get("text", "")
                    for block in response_content
                    if isinstance(block, (str, dict))
                ]
                text = "\n".join(part for part in text_blocks if part).strip()
                if text:
                    return text
            raise ValueError("The Gemini response did not contain text.")
        except Exception as exc:
            logger.exception(
                "Gemini request failed for model %s (%s).",
                settings.gemini_model_name,
                type(exc).__name__,
            )
            return fallback_reply("Gemini could not generate a response; check the backend log and Gemini settings.")

    def _trace_langfuse(self, event_name: str, payload: Dict[str, Any]) -> None:
        settings = get_settings()
        if not settings.langfuse_secret_key or not settings.langfuse_public_key or Langfuse is None:
            return
        try:
            langfuse = Langfuse(
                secret_key=settings.langfuse_secret_key,
                public_key=settings.langfuse_public_key,
                host=settings.langfuse_host,
            )
            trace = getattr(langfuse, "trace", None)
            if callable(trace):
                trace(name=event_name, input=payload, metadata=payload)
                return

            start_observation = getattr(langfuse, "start_observation", None)
            if callable(start_observation):
                observation = start_observation(
                    as_type="span",
                    name=event_name,
                    input=payload,
                    metadata=payload,
                )
                end_observation = getattr(observation, "end", None)
                if callable(end_observation):
                    end_observation()
                else:
                    logger.warning("Langfuse observation does not expose an end method.")
                return

            logger.warning("Langfuse SDK does not expose a supported tracing API.")
        except Exception:
            logger.exception("Langfuse tracing failed.")

    def process_chat_message(self, message_request: ChatMessage) -> Dict[str, Any]:
        session = self._get_session(message_request.session_id)
        goals_payload = message_request.goals
        if isinstance(goals_payload, list) and goals_payload:
            goals_payload = goals_payload[0]

        self._apply_session_updates(session, {
            "income": message_request.income,
            "currency": message_request.currency,
            "transactions": [txn.model_dump() for txn in message_request.transactions],
            "goals": goals_payload,
        })

        history = session.setdefault("chat_history", [])
        recent_history = history[-8:]
        conversation_context = "\n".join(
            f"{entry['role']}: {entry['content']}"
            for entry in recent_history
        )

        request = FinancialRequest(
            income=float(message_request.income or session.get("income", 0.0)),
            currency=message_request.currency,
            location=message_request.location,
            transactions=message_request.transactions,
            session_id=message_request.session_id,
            goal_name=(goals_payload or {}).get("name") if isinstance(goals_payload, dict) else None,
            goal_amount=(goals_payload or {}).get("target", 0.0) if isinstance(goals_payload, dict) else 0.0,
            goal_saved=(goals_payload or {}).get("saved", 0.0) if isinstance(goals_payload, dict) else 0.0,
        )
        analysis = self._build_analysis(session, request)

        prompt = (
            "You are the Personal Finance & Budget Advisor. Answer the user's latest question directly "
            "before offering advice. Keep the answer relevant to that question; do not attach a generic "
            "spending/savings recap to greetings, identity questions, or location questions. Use prior "
            "turns to resolve follow-up questions. Format multi-part answers as separate, point-by-point "
            "lines, not a summary paragraph; use one useful point per line and no table. Do not cap the "
            "response at 4-5 lines; include as many points as needed to fully answer. Mention financial "
            "figures only when they help answer the question, and do not repeat them from the prior reply "
            "unless needed. For cost-of-living questions, use the household size and available city; do not "
            "claim live prices or exact current costs without a live data source, and clearly label estimates. "
            "Use provided location context when relevant; it is geocoded place information only, not weather "
            "or live pricing data, and should not be quoted as a raw object. "
            f"All monetary amounts use {analysis['currency']}; use that currency consistently and do not "
            "use a different currency symbol. "
            f"Available location context: {analysis.get('location_context')}. "
            f"Recent conversation:\n{conversation_context or '(no earlier messages)'}\n"
            f"Latest user question: {message_request.message}\n"
            f"Financial context: {analysis}."
        )
        ai_reply = self._generate_ai_reply(
            prompt,
            analysis,
            user_message=message_request.message,
            location_context=analysis.get("location_context") or {},
        )
        history.extend([
            {"role": "user", "content": message_request.message},
            {"role": "assistant", "content": ai_reply},
        ])
        del history[:-12]
        self._trace_langfuse("finance_chat", {"message": message_request.message, "analysis": analysis})

        summary = {
            "reply": ai_reply,
            "session_id": self._session_key(message_request.session_id),
            "data": analysis,
        }
        return summary

    def analyze(self, request: FinancialRequest) -> Dict[str, Any]:
        session = self._get_session(request.session_id)
        self._apply_session_updates(session, {
            "income": request.income,
            "transactions": [txn.model_dump() for txn in request.transactions],
            "goals": {"name": request.goal_name, "target": request.goal_amount, "saved": request.goal_saved},
        })
        analysis = self._build_analysis(session, request)
        self._trace_langfuse("finance_analysis", {"request": request.model_dump(), "analysis": analysis})
        return analysis
