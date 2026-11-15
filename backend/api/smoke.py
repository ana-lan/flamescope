"""API smoke test: every GET endpoint against expected values. No server, no LLM calls.

Run (from backend/):  uv run python -m api.smoke
"""
from fastapi.testclient import TestClient

from api.main import app

N_TESTS, N_DUPLICATES = 1999, 46  # CFI 8 + SPICE 34 + E-Field 4


def main() -> None:
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}{'  -> ' + str(detail) if detail != '' else ''}")

    with TestClient(app) as c:  # "with" runs the lifespan warm-up
        j = c.get("/health").json()
        check("health ok", j["status"] == "ok",
              f"db={j['db']} index={j['index']} chain={len(j['llm_chain'])} warm={j['warm']} {j['warm_s']}s")

        j = c.get("/habitats").json()
        check("4 habitats", [h["slug"] for h in j] == ["iss", "gateway", "lunar", "apollo1"])

        j = c.get("/insights").json()
        check("5 insights in rank order", len(j) == 5 and [i["rank"] for i in j] == sorted(i["rank"] for i in j),
              [i["id"] for i in j])
        check("insights carry sources with DOI", all(s.get("doi") for i in j for s in i["sources"]),
              [(s["psi_id"], s.get("doi")) for s in j[0]["sources"]])
        j = c.get("/insights", params={"habitat": "lunar"}).json()
        check("insights?habitat=lunar", isinstance(j, list) and len(j) >= 1, [i["id"] for i in j])
        check("unknown habitat -> 422 (insights)", c.get("/insights", params={"habitat": "mars"}).status_code == 422)
        check("unknown habitat -> 422 (coverage)", c.get("/coverage", params={"habitat": "mars"}).status_code == 422)
        check("unknown habitat -> 422 (ask)", c.post("/ask", json={"question": "what about mars", "habitat": "mars"}).status_code == 422)
        spec = c.get("/openapi.json").json()
        enum = spec["paths"]["/coverage"]["get"]["parameters"][0]["schema"].get("enum")
        check("habitat enum published in OpenAPI", enum == ["iss", "gateway", "lunar", "apollo1"], enum)

        j = c.get("/tests", params={"include_duplicates": "true", "limit": 1}).json()
        check(f"tests total {N_TESTS} with duplicates", j["total"] == N_TESTS, j["total"])
        j = c.get("/tests", params={"limit": 1}).json()
        check(f"duplicates excluded by default ({N_TESTS - N_DUPLICATES})", j["total"] == N_TESTS - N_DUPLICATES,
              j["total"])
        j = c.get("/tests", params={"experiment": "FLEX", "outcome": "extinction", "limit": 5}).json()
        check("FLEX extinctions = 186, raw omitted", j["total"] == 186 and len(j["rows"]) == 5
              and "raw" not in j["rows"][0]["extra"], j["total"])
        r = c.get("/tests", params=[("experiment", "FLEX"), ("experiment", "CFI-G"), ("o2_min", 0.30),
                                    ("single_only", "true"), ("limit", 3)])
        check("repeatable filters + o2_min", r.status_code == 200 and r.json()["total"] > 0,
              f"total={r.json().get('total')}")
        check("limit over cap -> 422", c.get("/tests", params={"limit": 5000}).status_code == 422)
        check("o2 as percent -> 422", c.get("/tests", params={"o2_min": 30}).status_code == 422)
        r = c.get("/tests", params={"fuel": "x' or 1=1 --"})
        check("injection attempt is just a substring", r.status_code == 200 and r.json()["total"] == 0)

        j = c.get("/tests/facets").json()
        check("facets: 18 experiments", len(j["experiments"]) == 18,
              f"outcomes={[o['outcome'] for o in j['outcomes']]} fuels={len(j['fuels'])} ranges={j['ranges']}")

        j = c.get("/investigations").json()
        check("23 investigations", len(j) == 23, [i["psi_id"] for i in j[:5]])
        j = c.get("/investigations/psi-69").json()
        check("PSI-69 detail", j["investigation"]["doi"] == "10.60555/mbq8-0451" and j["publications"],
              f"{j['investigation']['acronym']} pubs={len(j['publications'])} tests={j['tests']['n_rows']}")
        check("unknown psi -> 404", c.get("/investigations/PSI-999").status_code == 404)

        r = c.get("/coverage", params={"habitat": "lunar"}, headers={"Accept-Encoding": "gzip"})
        j = r.json()
        check("coverage lunar: sparse, 11 in box", j["summary"]["verdict"] == "sparse"
              and j["summary"]["n_in_box"] == 11, f"points={len(j['points'])}")
        check("coverage is gzipped", r.headers.get("content-encoding") == "gzip")
        j = c.get("/coverage", params={"habitat": "iss"}).json()
        check("coverage iss: 235 in box", j["summary"]["n_in_box"] == 235)

        pre = {"Access-Control-Request-Method": "GET"}
        r = c.options("/habitats", headers={"Origin": "http://localhost:3000", **pre})
        check("CORS allows localhost:3000", r.headers.get("access-control-allow-origin") == "http://localhost:3000")
        r = c.options("/habitats", headers={"Origin": "https://ignit-iq-git-main-ana-lan.vercel.app", **pre})
        check("CORS allows Vercel preview", r.headers.get("access-control-allow-origin", "").endswith("vercel.app"))
        r = c.get("/habitats", headers={"Origin": "https://evil.example.com"})
        check("CORS blocks other origins", "access-control-allow-origin" not in r.headers)

    print("API: PASS" if ok else "API: FAIL")


if __name__ == "__main__":
    main()