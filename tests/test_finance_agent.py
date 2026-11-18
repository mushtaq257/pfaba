import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.app.models import ChatMessage, FinancialRequest, TransactionInput
from backend.app.services.finance_agent import FinanceAgent


class FinanceAgentAiTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {
            "currency": "INR",
            "total_spending": 25000,
            "remaining": 25000,
            "savings_rate": 50,
            "categories": {"Food": 10000, "Housing": 15000},
            "recommendations": [
                "Keep 20% of income for savings.",
                "Your heaviest spending area is Housing.",
            ],
        }

    @patch("backend.app.services.finance_agent.fetch_geolocation_context", return_value={})
    def test_analysis_uses_largest_category_total_and_classifies_loan_payments(
        self, fetch_geolocation
    ):
        request = FinancialRequest(
            income=80000,
            currency="INR",
            transactions=[
                TransactionInput(
                    description="Loan repayment",
                    amount=29000,
                    currency="INR",
                ),
                TransactionInput(
                    description="Entertainment subscription",
                    amount=1500,
                    currency="INR",
                    category="Entertainment",
                ),
            ],
        )

        analysis = FinanceAgent()._build_analysis({}, request)

        self.assertEqual(analysis["categories"]["Loan"], 29000)
        self.assertEqual(analysis["largest_category"], "Loan")
        self.assertEqual(analysis["largest_category_amount"], 29000)

    @patch("backend.app.services.finance_agent.fetch_geolocation_context")
    def test_analysis_classifies_expenses_tracks_goal_progress_and_uses_region(
        self, fetch_geolocation
    ):
        fetch_geolocation.return_value = {"city": "Pune", "country": "India"}
        request = FinancialRequest(
            income=100000,
            currency="INR",
            location="Pune",
            goal_name="Emergency",
            goal_amount=10000,
            goal_saved=2500,
            transactions=[
                TransactionInput(description="Rent payment", amount=1000, currency="INR"),
                TransactionInput(description="Coffee shop", amount=1000, currency="INR"),
                TransactionInput(description="Bus fare", amount=1000, currency="INR"),
                TransactionInput(description="Clothes shopping", amount=1000, currency="INR"),
                TransactionInput(description="Movie night", amount=1000, currency="INR"),
                TransactionInput(description="Flight hotel trip", amount=1000, currency="INR"),
                TransactionInput(description="Pharmacy visit", amount=1000, currency="INR"),
                TransactionInput(description="Monthly mutual fund SIP", amount=1000, currency="INR"),
                TransactionInput(description="Unlisted purchase", amount=1000, currency="INR"),
            ],
        )

        analysis = FinanceAgent()._build_analysis({}, request)

        self.assertEqual(
            set(analysis["categories"]),
            {
                "Housing",
                "Food",
                "Transport",
                "Shopping",
                "Entertainment",
                "Travel",
                "Health",
                "Investment",
                "Other",
            },
        )
        self.assertEqual(analysis["categories"]["Investment"], 1000)
        self.assertEqual(analysis["goals"][0]["progress"], 25)
        self.assertEqual(analysis["goals"][0]["remaining"], 7500)
        self.assertTrue(any("Pune" in item for item in analysis["recommendations"]))

        no_target_analysis = FinanceAgent()._build_analysis(
            {},
            FinancialRequest(
                income=1000,
                currency="INR",
                goal_name="Unfunded goal",
                goal_amount=0,
            ),
        )
        self.assertEqual(no_target_analysis["goals"][0]["progress"], 0)

    @patch("backend.app.services.finance_agent.convert_currency", return_value=82.5)
    def test_amount_conversion_skips_matching_currency_and_converts_other_currency(
        self, convert
    ):
        agent = FinanceAgent()

        self.assertEqual(agent._convert_amount(10, "INR", "INR"), 10)
        self.assertEqual(agent._convert_amount(1, "USD", "INR"), 82.5)

        convert.assert_called_once_with(1, "USD", "INR")

    @patch("backend.app.services.finance_agent.fetch_geolocation_context", return_value={})
    def test_analysis_alerts_when_savings_rate_is_below_ten_percent(self, fetch_geolocation):
        request = FinancialRequest(
            income=1000,
            currency="USD",
            transactions=[
                TransactionInput(
                    description="Food",
                    amount=950,
                    currency="USD",
                )
            ],
        )

        analysis = FinanceAgent()._build_analysis({}, request)

        self.assertEqual(analysis["savings_rate"], 5)
        self.assertIn(
            "Savings rate is below a healthy target of 10% to 20% of income.",
            analysis["alerts"],
        )

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.ChatGoogleGenerativeAI")
    def test_gemini_reply_uses_configured_base_url(self, gemini_model, get_settings):
        get_settings.return_value = SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model_name="gemini-test",
            gemini_base_url="https://gateway.example.com",
        )
        client = Mock()
        client.invoke.return_value = SimpleNamespace(content="Review your housing costs.")
        gemini_model.return_value = client

        reply = FinanceAgent()._generate_ai_reply("How can I save?", self.analysis)

        self.assertEqual(reply, "Review your housing costs.")
        gemini_model.assert_called_once_with(
            model="gemini-test",
            google_api_key="test-key",
            temperature=0.2,
            base_url="https://gateway.example.com",
        )
        client.invoke.assert_called_once_with("How can I save?")

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.FinanceAgent._build_lcel_chain")
    def test_ai_prompt_allows_long_point_by_point_answers(self, build_chain, get_settings):
        get_settings.return_value = SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model_name="gemini-test",
        )
        build_chain.return_value = Mock(invoke=Mock(return_value="Answer"))

        FinanceAgent()._generate_ai_reply("How do I build a budget?", self.analysis)

        system_message = build_chain.call_args.args[0]
        self.assertIn("separate, point-by-point lines", system_message)
        self.assertIn("Do not cap the response at 4-5 lines", system_message)
        self.assertIn("as many points as needed to fully answer", system_message)
        self.assertIn("Use provided location context when relevant", system_message)
        self.assertIn("not weather or live pricing data", system_message)

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.ChatGoogleGenerativeAI")
    def test_lcel_chain_builds_runnable_prompt_pipeline(self, gemini_model, get_settings):
        get_settings.return_value = SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model_name="gemini-test",
            gemini_base_url="https://gateway.example.com",
        )
        client = Mock()
        client.invoke.return_value = "LCEL answer"
        gemini_model.return_value = client

        chain = FinanceAgent()._build_lcel_chain("You are a helpful finance advisor.")

        self.assertIsNotNone(chain)
        self.assertEqual(chain.invoke("How can I save?"), "LCEL answer")
        self.assertEqual(chain.invoke({"input": "How can I save?"}), "LCEL answer")

    @patch("backend.app.services.finance_agent.get_settings")
    def test_lcel_chain_returns_none_without_api_key_or_missing_components(self, get_settings):
        get_settings.return_value = SimpleNamespace(gemini_api_key=None)
        self.assertIsNone(FinanceAgent()._build_lcel_chain("System prompt"))

        get_settings.return_value = SimpleNamespace(gemini_api_key="test-key")
        with patch("backend.app.services.finance_agent.ChatGoogleGenerativeAI", None):
            self.assertIsNone(FinanceAgent()._build_lcel_chain("System prompt"))

        with patch("backend.app.services.finance_agent.ChatPromptTemplate", None):
            self.assertIsNone(FinanceAgent()._build_lcel_chain("System prompt"))

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.ChatGoogleGenerativeAI")
    def test_generate_ai_reply_handles_none_chain_and_list_content(self, gemini_model, get_settings):
        get_settings.return_value = SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model_name="gemini-test",
            gemini_base_url=None,
        )
        gemini_model.return_value = Mock()

        with patch.object(FinanceAgent, "_build_lcel_chain", return_value=None):
            reply = FinanceAgent()._generate_ai_reply("prompt", self.analysis, user_message="hello")
            self.assertIn("Hello!", reply)

        chain = Mock()
        chain.invoke.return_value = SimpleNamespace(content=["First point", {"text": "Second point"}, {"other": "ignored"}])
        with patch.object(FinanceAgent, "_build_lcel_chain", return_value=chain):
            reply = FinanceAgent()._generate_ai_reply("prompt", self.analysis)
            self.assertEqual(reply, "First point\nSecond point")

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.ChatGoogleGenerativeAI")
    def test_lcel_chain_normalizes_message_objects_and_list_content(self, gemini_model, get_settings):
        get_settings.return_value = SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model_name="gemini-test",
            gemini_base_url="https://gateway.example.com",
        )
        client = Mock()
        client.invoke.return_value = SimpleNamespace(content=["First point", {"text": "Second point"}, {"other": "ignored"}])
        gemini_model.return_value = client

        chain = FinanceAgent()._build_lcel_chain("You are a helpful finance advisor.")
        prompt_messages = SimpleNamespace(messages=[
            SimpleNamespace(content="hello"),
            SimpleNamespace(content="How can I save?"),
        ])

        self.assertEqual(chain.invoke(prompt_messages), "First point\nSecond point")

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.ChatGoogleGenerativeAI")
    def test_lcel_lambda_handles_text_dict_input_and_raises_for_empty_text(self, gemini_model, get_settings):
        get_settings.return_value = SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model_name="gemini-test",
            gemini_base_url="https://gateway.example.com",
        )
        client = Mock()
        client.invoke.return_value = SimpleNamespace(content="Follow the plan.")
        gemini_model.return_value = client

        chain = FinanceAgent()._build_lcel_chain("You are a helpful finance advisor.")
        model_step = chain.steps[1]

        self.assertEqual(model_step.invoke({"text": "How can I save?"}), "Follow the plan.")
        self.assertEqual(model_step.invoke(SimpleNamespace(messages=[])), "Follow the plan.")
        self.assertEqual(model_step.invoke(42), "Follow the plan.")
        client.invoke.assert_called_with(42)

        chain_response = Mock()
        chain_response.invoke.return_value = SimpleNamespace(content=[{"other": "ignored"}])
        with patch.object(FinanceAgent, "_build_lcel_chain", return_value=chain_response):
            with self.assertLogs("backend.app.services.finance_agent", level="ERROR") as logs:
                reply = FinanceAgent()._generate_ai_reply("prompt", self.analysis)

        self.assertIn("Gemini could not generate a response", reply)
        self.assertTrue(any("Gemini request failed" in line for line in logs.output))

    @patch("backend.app.services.finance_agent.get_settings")
    def test_missing_gemini_key_returns_useful_local_finance_reply(self, get_settings):
        get_settings.return_value = SimpleNamespace(gemini_api_key=None)

        reply = FinanceAgent()._generate_ai_reply("How can I save?", self.analysis)

        self.assertIn("GEMINI_API_KEY is empty", reply)
        self.assertIn("25,000.00 INR", reply)
        self.assertIn("Highest spending category: Housing", reply)
        self.assertGreaterEqual(len(reply.splitlines()), 5)
        self.assertTrue(reply.splitlines()[1].startswith("Spending:"))

    @patch("backend.app.services.finance_agent.ChatGoogleGenerativeAI", None)
    @patch("backend.app.services.finance_agent.get_settings")
    def test_missing_gemini_integration_uses_question_specific_local_reply(self, get_settings):
        get_settings.return_value = SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model_name="gemini-test",
        )

        reply = FinanceAgent()._generate_ai_reply(
            "prompt",
            self.analysis,
            user_message="hello",
        )

        self.assertIn("Hello!", reply)
        self.assertNotIn("Highest spending category", reply)

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.ChatGoogleGenerativeAI")
    def test_gemini_text_blocks_are_joined_and_empty_response_falls_back(
        self, gemini_model, get_settings
    ):
        get_settings.return_value = SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model_name="gemini-test",
            gemini_base_url=None,
        )
        client = Mock()
        client.invoke.side_effect = [
            SimpleNamespace(content=["First point", {"text": "Second point"}, {"other": "ignored"}]),
            SimpleNamespace(content=[]),
            SimpleNamespace(content=None),
        ]
        gemini_model.return_value = client
        agent = FinanceAgent()

        self.assertEqual(
            agent._generate_ai_reply("prompt", self.analysis),
            "First point\nSecond point",
        )
        self.assertIn(
            "Gemini could not generate a response",
            agent._generate_ai_reply("prompt", self.analysis),
        )
        self.assertIn(
            "Gemini could not generate a response",
            agent._generate_ai_reply("prompt", self.analysis),
        )
        self.assertEqual(gemini_model.call_args.kwargs.get("base_url"), None)

    def test_local_finance_reply_handles_empty_categories_and_recommendations(self):
        reply = FinanceAgent._local_finance_reply(
            {
                "currency": "INR",
                "total_spending": 0,
                "remaining": 1000,
                "savings_rate": 100,
                "categories": {},
                "recommendations": [],
            },
            "Local fallback",
        )

        self.assertIn("Local fallback", reply)
        self.assertNotIn("Highest spending category", reply)
        self.assertNotIn("Next step:", reply)

    def test_local_chat_fallback_covers_greeting_city_cost_savings_spending_and_default(self):
        analysis = {
            **self.analysis,
            "total_spending": 25000,
            "remaining": 25000,
            "savings_rate": 50,
        }

        self.assertIn(
            "Hello!",
            FinanceAgent._local_chat_reply("hello", analysis, {}, "fallback"),
        )
        self.assertIn(
            "Personal Finance & Budget Advisor",
            FinanceAgent._local_chat_reply("who are you?", analysis, {}, "fallback"),
        )
        self.assertIn(
            "confirmed city",
            FinanceAgent._local_chat_reply("what is my current city?", analysis, {}, "fallback"),
        )
        self.assertIn(
            "Location available",
            FinanceAgent._local_chat_reply(
                "what is the current city?", analysis, {"city": "Pune"}, "fallback"
            ),
        )
        self.assertIn(
            "I need your city",
            FinanceAgent._local_chat_reply("cost of living?", analysis, {}, "fallback"),
        )
        self.assertIn(
            "Pune",
            FinanceAgent._local_chat_reply(
                "cost of living?", analysis, {"city": "Pune"}, "fallback"
            ),
        )
        self.assertIn(
            "Savings rate",
            FinanceAgent._local_chat_reply("how are my savings?", analysis, {}, "fallback"),
        )
        self.assertIn(
            "Largest category: Housing",
            FinanceAgent._local_chat_reply("what are my expenses?", analysis, {}, "fallback"),
        )
        self.assertNotIn(
            "Largest category:",
            FinanceAgent._local_chat_reply(
                "what are my expenses?", {**analysis, "categories": {}}, {}, "fallback"
            ),
        )
        self.assertIn(
            "Try asking",
            FinanceAgent._local_chat_reply("tell me about my goals", analysis, {}, "fallback"),
        )

    @patch("backend.app.services.finance_agent.get_settings")
    def test_local_chat_fallback_answers_identity_and_city_questions_directly(self, get_settings):
        get_settings.return_value = SimpleNamespace(gemini_api_key=None)
        agent = FinanceAgent()

        identity = agent._generate_ai_reply(
            "prompt",
            self.analysis,
            user_message="Which AI agent are you?",
        )
        city = agent._generate_ai_reply(
            "prompt",
            self.analysis,
            user_message="What is the current city?",
            location_context={"city": "Pune"},
        )

        self.assertIn("Personal Finance & Budget Advisor", identity)
        self.assertNotIn("Savings rate", identity)
        self.assertEqual(city, "Location available in your finance profile: Pune.")

    @patch("backend.app.services.finance_agent.fetch_geolocation_context", return_value={"city": "Pune"})
    @patch("backend.app.services.finance_agent.FinanceAgent._trace_langfuse")
    @patch("backend.app.services.finance_agent.FinanceAgent._generate_ai_reply")
    def test_chat_prompt_includes_recent_turns_and_location(
        self, generate_reply, trace_langfuse, fetch_geolocation
    ):
        generate_reply.side_effect = ["Pune is the city in your profile.", "A location-specific estimate needs local costs."]
        agent = FinanceAgent()

        agent.process_chat_message(ChatMessage(
            message="What is the current city?",
            session_id="auth0|alice",
            currency="INR",
            location="Pune",
        ))
        agent.process_chat_message(ChatMessage(
            message="What is cost of living for a family of four?",
            session_id="auth0|alice",
            currency="INR",
            location="Pune",
        ))

        follow_up_prompt = generate_reply.call_args_list[1].args[0]
        self.assertIn("Recent conversation:", follow_up_prompt)
        self.assertIn("user: What is the current city?", follow_up_prompt)
        self.assertIn("assistant: Pune is the city in your profile.", follow_up_prompt)
        self.assertIn("'city': 'Pune'", follow_up_prompt)
        self.assertIn("Use provided location context when relevant", follow_up_prompt)

    @patch("backend.app.services.finance_agent.FinanceAgent._trace_langfuse")
    @patch("backend.app.services.finance_agent.FinanceAgent._generate_ai_reply")
    @patch("backend.app.services.finance_agent.fetch_geolocation_context", return_value={})
    def test_chat_analysis_and_prompt_use_selected_currency(
        self, fetch_geolocation, generate_reply, trace_langfuse
    ):
        generate_reply.return_value = "You are doing well."
        request = ChatMessage(
            message="How are my savings?",
            session_id="inr-session",
            income=50000,
            currency="INR",
            transactions=[
                TransactionInput(
                    description="Rent",
                    amount=18000,
                    currency="INR",
                )
            ],
            goals=[{"name": "Emergency", "target": 10000, "saved": 2000}],
        )

        result = FinanceAgent().process_chat_message(request)

        self.assertEqual(result["data"]["currency"], "INR")
        self.assertEqual(result["data"]["goals"][0]["progress"], 20)
        prompt = generate_reply.call_args.args[0]
        self.assertIn("All monetary amounts use INR", prompt)
        self.assertIn("not a summary paragraph", prompt)
        self.assertIn("use one useful point per line", prompt)
        self.assertIn("Do not cap the response at 4-5 lines", prompt)
        self.assertNotIn("currency='USD'", prompt)

    @patch("backend.app.services.finance_agent.FinanceAgent._trace_langfuse")
    @patch("backend.app.services.finance_agent.fetch_geolocation_context", return_value={})
    def test_analyze_returns_financial_analysis_and_traces_the_request(
        self, fetch_geolocation, trace_langfuse
    ):
        request = FinancialRequest(
            income=1000,
            currency="USD",
            session_id="auth0|alice",
            transactions=[TransactionInput(description="Rent", amount=200)],
        )

        analysis = FinanceAgent().analyze(request)

        self.assertEqual(analysis["remaining"], 800)
        self.assertEqual(analysis["largest_category"], "Housing")
        trace_langfuse.assert_called_once()
        self.assertEqual(trace_langfuse.call_args.args[0], "finance_analysis")

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.Langfuse")
    def test_langfuse_v3_records_an_observation(self, langfuse_client, get_settings):
        get_settings.return_value = SimpleNamespace(
            langfuse_secret_key="secret",
            langfuse_public_key="public",
            langfuse_host="https://cloud.langfuse.com",
        )
        observation = Mock()
        client = Mock(spec=["start_observation"])
        client.start_observation.return_value = observation
        langfuse_client.return_value = client
        payload = {"total_spending": 25000}

        FinanceAgent()._trace_langfuse("finance_analysis", payload)

        client.start_observation.assert_called_once_with(
            as_type="span",
            name="finance_analysis",
            input=payload,
            metadata=payload,
        )
        observation.end.assert_called_once_with()

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.Langfuse")
    def test_langfuse_uses_trace_api_when_available(self, langfuse_client, get_settings):
        get_settings.return_value = SimpleNamespace(
            langfuse_secret_key="secret",
            langfuse_public_key="public",
            langfuse_host="https://cloud.langfuse.com",
        )
        client = Mock(spec=["trace"])
        langfuse_client.return_value = client
        payload = {"total_spending": 10}

        FinanceAgent()._trace_langfuse("finance_analysis", payload)

        client.trace.assert_called_once_with(
            name="finance_analysis",
            input=payload,
            metadata=payload,
        )

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.Langfuse")
    def test_langfuse_warns_when_sdk_has_no_supported_trace_api(
        self, langfuse_client, get_settings
    ):
        get_settings.return_value = SimpleNamespace(
            langfuse_secret_key="secret",
            langfuse_public_key="public",
            langfuse_host="https://cloud.langfuse.com",
        )
        langfuse_client.return_value = SimpleNamespace()

        with self.assertLogs("backend.app.services.finance_agent", level="WARNING") as logs:
            FinanceAgent()._trace_langfuse("finance_analysis", {})

        self.assertIn("does not expose a supported tracing API", logs.output[0])

    @patch("backend.app.services.finance_agent.get_settings")
    @patch("backend.app.services.finance_agent.Langfuse")
    def test_langfuse_warns_when_observation_cannot_be_ended(
        self, langfuse_client, get_settings
    ):
        get_settings.return_value = SimpleNamespace(
            langfuse_secret_key="secret",
            langfuse_public_key="public",
            langfuse_host="https://cloud.langfuse.com",
        )
        langfuse_client.return_value = SimpleNamespace(
            start_observation=Mock(return_value=SimpleNamespace())
        )

        with self.assertLogs("backend.app.services.finance_agent", level="WARNING") as logs:
            FinanceAgent()._trace_langfuse("finance_analysis", {})

        self.assertIn("does not expose an end method", logs.output[0])

    @patch("backend.app.services.finance_agent.get_settings")
    @patch(
        "backend.app.services.finance_agent.Langfuse",
        side_effect=RuntimeError("Langfuse unavailable"),
    )
    def test_langfuse_logs_client_failures_without_breaking_analysis(
        self, langfuse_client, get_settings
    ):
        get_settings.return_value = SimpleNamespace(
            langfuse_secret_key="secret",
            langfuse_public_key="public",
            langfuse_host="https://cloud.langfuse.com",
        )

        with self.assertLogs("backend.app.services.finance_agent", level="ERROR") as logs:
            FinanceAgent()._trace_langfuse("finance_analysis", {})

        self.assertIn("Langfuse tracing failed", logs.output[0])

    @patch("backend.app.services.finance_agent.Langfuse")
    @patch("backend.app.services.finance_agent.get_settings")
    def test_langfuse_is_skipped_when_credentials_are_missing(self, get_settings, langfuse_client):
        get_settings.return_value = SimpleNamespace(
            langfuse_secret_key=None,
            langfuse_public_key="public",
            langfuse_host=None,
        )

        FinanceAgent()._trace_langfuse("finance_analysis", {})

        langfuse_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
