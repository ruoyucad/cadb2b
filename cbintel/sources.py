"""Official CanadaBuys open-data files (Open Government Licence - Canada).

Dataset pages:
  Contract history: https://open.canada.ca/data/en/dataset/4fe645a1-ffcd-40c1-9385-2c771be956a4
  Award notices:    https://open.canada.ca/data/en/dataset/a1acb126-9ce8-40a9-b889-5da2b1dd20cb
  Tender notices:   https://open.canada.ca/data/en/dataset/6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2
Data dictionary:    https://donnees-data.tpsgc-pwgsc.gc.ca/ba2/ac-cb/achatscanada-canadabuys-dd.xml

Attribution required when republishing:
  "Contains information licensed under the Open Government Licence – Canada."
"""

BASE = "https://canadabuys.canada.ca/opendata/pub/"

# name -> (url, group). Groups map to staging tables.
SOURCES = {
    # Who won what — the core of the product. Has supplier legal/standardized names,
    # supplier address, employee count and % of goods by country of origin.
    "contract_history_current": (BASE + "contractHistoryComplete-contratsOctroyesComplet.csv", "contract_history"),
    "contract_history_legacy": (BASE + "2009-2023-contractHistoryHistorical-contratsOctroyesHistorique.csv", "contract_history"),
    # Award notices (published award announcements, 2022-08 onward + legacy).
    "award_notices_current": (BASE + "awardNoticeComplete-avisAttributionComplet.csv", "award_notices"),
    "award_notices_legacy": (BASE + "2012-2022-awardNoticeHistorical-avisAttributionHistorique.csv", "award_notices"),
    # Tenders. "open" = currently accepting bids (refreshed daily),
    # "new" = latest notices/amendments (refreshed every ~2h).
    "tenders_open": (BASE + "openTenderNotice-ouvertAvisAppelOffres.csv", "tenders"),
    "tenders_new": (BASE + "newTenderNotice-nouvelAvisAppelOffres.csv", "tenders"),
}

# Small subset for a fast first run (`--quick`): skips the large legacy files.
QUICK = ["contract_history_current", "award_notices_current", "tenders_open"]
