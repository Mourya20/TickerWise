import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import get_instrument, health, search_instruments
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Company, DailyMarketSnapshot, DataSource, Instrument, InstrumentShareCount


class StockSearchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine)
        with cls.session_factory() as session:
            company_one = Company(id=1, name="Reliance Industries Limited")
            company_two = Company(id=2, name="Reliance Power Limited")
            company_three = Company(id=3, name="Infosys Limited")
            company_four = Company(id=4, name="Tata Consultancy Services Limited")
            session.add_all([company_one, company_two, company_three, company_four])
            session.add_all(
                [
                    Instrument(
                        id=101,
                        company_id=1,
                        exchange="NSE",
                        symbol="RELIANCE",
                        series="EQ",
                        instrument_type="EQUITY",
                        isin="INE002A01018",
                        is_active=True,
                    ),
                    Instrument(
                        id=102,
                        company_id=1,
                        exchange="NSE",
                        symbol="RELIANCE",
                        series="BE",
                        instrument_type="EQUITY",
                        isin=None,
                        is_active=True,
                    ),
                    Instrument(
                        id=103,
                        company_id=2,
                        exchange="NSE",
                        symbol="RPOWER",
                        series="EQ",
                        instrument_type="EQUITY",
                        isin=None,
                        is_active=True,
                    ),
                    Instrument(
                        id=104,
                        company_id=3,
                        exchange="NSE",
                        symbol="INFY",
                        series="EQ",
                        instrument_type="EQUITY",
                        isin=None,
                        is_active=True,
                    ),
                    Instrument(
                        id=105,
                        company_id=4,
                        exchange="NSE",
                        symbol="TCS",
                        series="EQ",
                        instrument_type="EQUITY",
                        isin="INE467B01029",
                        is_active=True,
                    ),
                ]
            )
            session.add(DataSource(id=201, name="test-source", source_type="test"))
            session.add(
                DailyMarketSnapshot(
                    id=301,
                    instrument_id=101,
                    source_id=201,
                    snapshot_date=date(2026, 10, 14),
                    last_traded_price=Decimal("2304.9"),
                    percentage_change_pct=Decimal("2.11"),
                    market_capitalization_crores=Decimal("833932.99"),
                    volume_lakhs=Decimal("121.46"),
                    traded_value_crores=Decimal("2805.17"),
                )
            )
            session.add(
                DailyMarketSnapshot(
                    id=302,
                    instrument_id=105,
                    source_id=201,
                    snapshot_date=date(2026, 10, 14),
                    last_traded_price=Decimal("2304.900000"),
                    percentage_change_pct=Decimal("2.110000"),
                    market_capitalization_crores=Decimal("833932.990000"),
                    volume_lakhs=Decimal("121.460000"),
                    traded_value_crores=Decimal("2805.170000"),
                )
            )
            session.add(
                InstrumentShareCount(
                    id=501,
                    instrument_id=105,
                    symbol="TCS",
                    series="EQ",
                    share_class="EQUITY",
                    reporting_date=date(2026, 9, 30),
                    reported_share_count=1000000000,
                    fully_paid_shares=1000000000,
                    source_id=201,
                    extraction_method="xbrl",
                    validation_status="verified",
                )
            )
            session.commit()
        def override_db():
            with cls.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        self.session = self.session_factory()

    def tearDown(self):
        self.session.close()

    def test_exact_symbol_search(self):
        results = search_instruments("INFY", 20, 0, self.session)
        self.assertEqual([result.instrument_id for result in results], [104])

    def test_health_endpoint(self):
        self.assertEqual(health(), {"status": "ok"})

    def test_partial_company_name_search(self):
        results = search_instruments("Power", 20, 0, self.session)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].symbol, "RPOWER")

    def test_search_is_case_insensitive(self):
        results = search_instruments("infy", 20, 0, self.session)
        self.assertEqual(results[0].company_name, "Infosys Limited")

    def test_empty_query_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            search_instruments("   ", 20, 0, self.session)
        self.assertEqual(error.exception.status_code, 400)

    def test_pagination_is_predictable(self):
        first_page = search_instruments("RELIANCE", 1, 0, self.session)
        second_page = search_instruments("RELIANCE", 1, 1, self.session)
        self.assertEqual(first_page[0].instrument_id, 102)
        self.assertEqual(second_page[0].instrument_id, 101)

    def test_multiple_series_are_returned(self):
        results = search_instruments("RELIANCE", 100, 0, self.session)
        self.assertEqual({result.series for result in results}, {"EQ", "BE"})

    def test_detail_includes_snapshot_with_units(self):
        result = get_instrument(101, self.session)
        self.assertEqual(result.symbol, "RELIANCE")
        self.assertEqual(result.snapshot.snapshot_date, date(2026, 10, 14))
        self.assertEqual(result.snapshot.ltp, Decimal("2304.900000"))
        # When no official share count exists, market_cap is unavailable (None) without silent fallback
        self.assertIsNone(result.snapshot.market_capitalization_crores)
        self.assertEqual(result.snapshot.share_count_status, "unavailable")
        self.assertEqual(result.snapshot.volume_lakhs, Decimal("121.460000"))
        self.assertEqual(result.snapshot.traded_value_crores, Decimal("2805.170000"))

    def test_detail_without_snapshot_returns_null_snapshot(self):
        result = get_instrument(104, self.session)
        self.assertIsNone(result.snapshot)

    def test_unknown_instrument_returns_404(self):
        with self.assertRaises(HTTPException) as error:
            get_instrument(999999, self.session)
        self.assertEqual(error.exception.status_code, 404)

    def test_openapi_documents_bounded_pagination(self):
        from app.main import app

        parameters = app.openapi()["paths"]["/api/v1/instruments"]["get"]["parameters"]
        by_name = {parameter["name"]: parameter for parameter in parameters}
        self.assertEqual(by_name["limit"]["schema"]["maximum"], 100)
        self.assertEqual(by_name["offset"]["schema"]["minimum"], 0)

    def test_database_error_returns_503(self):
        class BrokenSession:
            def execute(self, statement):
                raise SQLAlchemyError("internal database detail")

            def rollback(self):
                pass

        with self.assertRaises(HTTPException) as error:
            search_instruments("RELIANCE", 20, 0, BrokenSession())
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(error.exception.detail, "Database service is unavailable.")

    def test_http_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_http_search_tcs_returns_correct_json_structure(self):
        response = self.client.get("/api/v1/instruments", params={"query": "TCS"})
        self.assertEqual(response.status_code, 200)
        results = response.json()
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        tcs = results[0]
        self.assertEqual(tcs["instrument_id"], 105)
        self.assertEqual(tcs["symbol"], "TCS")
        self.assertEqual(tcs["company_name"], "Tata Consultancy Services Limited")
        self.assertEqual(tcs["exchange"], "NSE")
        self.assertEqual(tcs["series"], "EQ")
        self.assertEqual(tcs["isin"], "INE467B01029")
        self.assertTrue(tcs["is_active"])

    def test_http_search_by_partial_company_name(self):
        response = self.client.get("/api/v1/instruments", params={"query": "Consultancy"})
        self.assertEqual(response.status_code, 200)
        results = response.json()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["symbol"], "TCS")

        response_power = self.client.get("/api/v1/instruments", params={"query": "Power"})
        self.assertEqual(response_power.status_code, 200)
        results_power = response_power.json()
        self.assertEqual(len(results_power), 1)
        self.assertEqual(results_power[0]["symbol"], "RPOWER")

    def test_http_search_is_case_insensitive(self):
        res_upper = self.client.get("/api/v1/instruments", params={"query": "TCS"}).json()
        res_lower = self.client.get("/api/v1/instruments", params={"query": "tcs"}).json()
        res_mixed = self.client.get("/api/v1/instruments", params={"query": "Tcs"}).json()
        self.assertEqual(res_upper, res_lower)
        self.assertEqual(res_lower, res_mixed)

    def test_http_empty_queries_and_invalid_pagination(self):
        # Empty whitespace query -> 400
        res_ws = self.client.get("/api/v1/instruments", params={"query": "   "})
        self.assertEqual(res_ws.status_code, 400)
        self.assertEqual(res_ws.json()["detail"], "Query must contain non-whitespace text.")

        # Empty string query (min_length=1) -> 422
        res_empty = self.client.get("/api/v1/instruments", params={"query": ""})
        self.assertEqual(res_empty.status_code, 422)

        # Missing query parameter -> 422
        res_missing = self.client.get("/api/v1/instruments")
        self.assertEqual(res_missing.status_code, 422)

        # Limit out of range (ge=1, le=100) -> 422
        res_limit_zero = self.client.get("/api/v1/instruments", params={"query": "TCS", "limit": 0})
        self.assertEqual(res_limit_zero.status_code, 422)

        res_limit_over = self.client.get("/api/v1/instruments", params={"query": "TCS", "limit": 101})
        self.assertEqual(res_limit_over.status_code, 422)

        # Negative offset (ge=0) -> 422
        res_offset_neg = self.client.get("/api/v1/instruments", params={"query": "TCS", "offset": -1})
        self.assertEqual(res_offset_neg.status_code, 422)

    def test_http_valid_instrument_detail_request(self):
        response = self.client.get("/api/v1/instruments/105")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        expected_keys = {
            "instrument_id",
            "company_id",
            "company_name",
            "exchange",
            "symbol",
            "series",
            "instrument_type",
            "isin",
            "listing_date",
            "paid_up_value",
            "market_lot",
            "face_value",
            "is_active",
            "snapshot",
        }
        self.assertTrue(expected_keys.issubset(data.keys()))
        self.assertEqual(data["instrument_id"], 105)
        self.assertEqual(data["company_name"], "Tata Consultancy Services Limited")
        self.assertEqual(data["symbol"], "TCS")
        self.assertEqual(data["series"], "EQ")
        self.assertEqual(data["isin"], "INE467B01029")
        self.assertIsNotNone(data["snapshot"])

    def test_http_instrument_without_snapshot_remains_accessible(self):
        response = self.client.get("/api/v1/instruments/104")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["symbol"], "INFY")
        self.assertEqual(data["company_name"], "Infosys Limited")
        self.assertIsNone(data["snapshot"])

    def test_http_unknown_instrument_id_returns_404(self):
        response = self.client.get("/api/v1/instruments/999999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Instrument not found.")

    def test_http_decimal_values_accurately_represented(self):
        response = self.client.get("/api/v1/instruments/105")
        self.assertEqual(response.status_code, 200)
        snapshot = response.json()["snapshot"]
        self.assertEqual(snapshot["ltp"], "2304.900000")
        self.assertEqual(snapshot["percentage_change_pct"], "2.110000")
        self.assertEqual(Decimal(snapshot["ltp"]), Decimal("2304.900000"))
        self.assertEqual(Decimal(snapshot["percentage_change_pct"]), Decimal("2.110000"))

    def test_http_snapshot_date_and_units_are_correct(self):
        response = self.client.get("/api/v1/instruments/105")
        self.assertEqual(response.status_code, 200)
        snapshot = response.json()["snapshot"]
        self.assertEqual(snapshot["snapshot_date"], "2026-10-14")
        self.assertEqual(snapshot["market_capitalization_crores"], "230490.000000")
        self.assertEqual(snapshot["share_count"], 1000000000)
        self.assertEqual(snapshot["share_count_status"], "fresh")
        self.assertEqual(snapshot["volume_lakhs"], "121.460000")
        self.assertEqual(snapshot["traded_value_crores"], "2805.170000")

    def test_http_error_responses_do_not_expose_sql_or_secrets(self):
        resp_404 = self.client.get("/api/v1/instruments/999999")
        self.assertEqual(resp_404.status_code, 404)
        for keyword in ["sql", "select", "traceback", "password", "sqlalchemy"]:
            self.assertNotIn(keyword, resp_404.text.lower())

        resp_400 = self.client.get("/api/v1/instruments", params={"query": "   "})
        self.assertEqual(resp_400.status_code, 400)
        for keyword in ["sql", "select", "traceback", "password", "sqlalchemy"]:
            self.assertNotIn(keyword, resp_400.text.lower())

        # 503 simulation with sensitive internal query failure
        def broken_db():
            class BrokenSession:
                def execute(self, statement):
                    raise SQLAlchemyError("SELECT secret_token FROM internal_secrets WHERE user='root'")

                def rollback(self):
                    pass

            yield BrokenSession()

        app.dependency_overrides[get_db] = broken_db
        try:
            resp_503 = self.client.get("/api/v1/instruments", params={"query": "TCS"})
            self.assertEqual(resp_503.status_code, 503)
            self.assertEqual(resp_503.json()["detail"], "Database service is unavailable.")
            for keyword in ["secret", "token", "root", "select", "password", "traceback", "sqlalchemy"]:
                self.assertNotIn(keyword, resp_503.text.lower())
        finally:
            def restore_db():
                with self.session_factory() as session:
                    yield session

            app.dependency_overrides[get_db] = restore_db


if __name__ == "__main__":
    unittest.main()
