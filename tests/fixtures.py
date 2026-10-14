"""Tiny synthetic CSVs using the real CanadaBuys bilingual headers (from the
official data dictionary), so the pipeline can be tested without network."""
import csv
from pathlib import Path

# (base header, bilingual?) — bilingual ones get '-eng' and '-fra' columns.
CH = [
    ("amendmentDate-dateModification", 0), ("amendmentNumber-numeroModification", 0),
    ("contractAmount-montantContrat", 0), ("contractAwardDate-dateAttributionContrat", 0),
    ("contractCurrency-contratMonnaie", 0), ("contractEndDate-dateFinContrat", 0),
    ("contractingEntityName-nomEntitContractante", 1), ("contractNumber-numeroContrat", 0),
    ("contractStartDate-contratDateDebut", 0), ("endUserEntitiesName-nomEntitesUtilisateurFinal", 1),
    ("gsin-nibs", 0), ("gsinDescription-nibsDescription", 1),
    ("percentageOfGoodsByCountry-pourcentageDeBiensParPays", 0),
    ("procurementCategory-categorieApprovisionnement", 0),
    ("procurementMethod-methodeApprovisionnement", 1), ("referenceNumber-numeroReference", 0),
    ("solicitationNumber-numeroSollicitation", 0),
    ("supplierAddressCity-fournisseurAdresseVille", 1), ("supplierAddressCountry-fournisseurAdressePays", 1),
    ("supplierAddressLine-ligneAdresseFournisseur", 1), ("supplierAddressPostalCode-fournisseurAdresseCodePostal", 0),
    ("supplierAddressProvince-fournisseurAdresseProvince", 1),
    ("supplierEmployeeCount-fournisseurNombreEmployes", 1), ("supplierLegalName-nomLegalFournisseur", 1),
    ("supplierOperatingName-nomCommercialFournisseur", 1),
    ("supplierStandardizedName-nomNormaliseFournisseur", 1),
    ("title-titre", 1), ("totalContractValue-valeurTotaleContrat", 0),
    ("unspsc", 0), ("unspscDescription", 1),
]
AN = [h for h in CH if not h[0].startswith(("supplierEmployee", "supplierOperating",
                                            "supplierStandardized", "percentageOfGoods"))]
AN += [("awardDescription-descriptionAttribution", 1)]
TN = [
    ("amendmentDate-dateModification", 0), ("amendmentNumber-numeroModification", 0),
    ("contactInfoEmail-informationsContactCourriel", 0), ("contactInfoName-informationsContactNom", 0),
    ("contactInfoPhone-contactInfoTelephone", 0),
    ("contractingEntityName-nomEntitContractante", 1), ("gsin-nibs", 0),
    ("noticeURL-URLavis", 1), ("procurementCategory-categorieApprovisionnement", 0),
    ("publicationDate-datePublication", 0), ("referenceNumber-numeroReference", 0),
    ("regionsOfDelivery-regionsLivraison", 1), ("solicitationNumber-numeroSollicitation", 0),
    ("tenderClosingDate-appelOffresDateCloture", 0), ("tenderDescription-descriptionAppelOffres", 1),
    ("tenderStatus-appelOffresStatut", 1), ("title-titre", 1),
    ("tradeAgreements-accordsCommerciaux", 1), ("unspsc", 0), ("unspscDescription", 1),
]


def _headers(spec):
    out = []
    for h, bi in spec:
        out += [f"{h}-eng", f"{h}-fra"] if bi else [h]
    return out


def _write(path: Path, spec, rows):
    hs = _headers(spec)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # BOM like the real files
        w = csv.DictWriter(f, fieldnames=hs)
        w.writeheader()
        for r in rows:
            row = {}
            for h, bi in spec:
                key = h.split("-")[0]
                v = r.get(key, "")
                if bi:
                    row[f"{h}-eng"], row[f"{h}-fra"] = v, f"FR {v}" if v else ""
                else:
                    row[h] = v
            w.writerow(row)


def _ch(no, amend, supplier_legal, std, value, total, date, unspsc, desc, cat="*GD", city="Toronto",
        prov="Ontario", country="Canada", origin="", buyer="Public Services and Procurement Canada"):
    return dict(contractNumber=no, amendmentNumber=amend, amendmentDate=date, contractAwardDate=date,
                contractAmount=value, totalContractValue=total, supplierLegalName=supplier_legal,
                supplierStandardizedName=std, supplierAddressCity=city, supplierAddressProvince=prov,
                supplierAddressCountry=country, supplierEmployeeCount="50-99", contractingEntityName=buyer,
                procurementCategory=cat, unspsc=unspsc, unspscDescription=desc, title=desc,
                percentageOfGoodsByCountry=origin)


def write_fixtures(raw: Path) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    ch = [
        # Same company, three spellings, one with an amendment -> should merge to one supplier.
        _ch("C-001", "000", "Acme Safety Supply Inc.", "ACME SAFETY SUPPLY", "100000", "100000",
            "2025-03-01", "46181504", "Protective gloves", origin="CN 60%, CA 40%"),
        _ch("C-001", "001", "Acme Safety Supply Inc.", "ACME SAFETY SUPPLY", "20000", "120000",
            "2025-06-01", "46181504", "Protective gloves"),
        _ch("C-002", "000", "ACME SAFETY SUPPLY LTD", "ACME SAFETY SUPPLY", "$50,000.00", "",
            "2024-02-10", "46181601", "Safety boots", buyer="Department of National Defence"),
        _ch("C-003", "000", "Acmé Safety Supply Ltée", "", "30000", "30000",
            "2023-11-15", "46181504", "Protective gloves", prov="Quebec", city="Montréal"),
        # Furniture supplier.
        _ch("C-004", "000", "Northern Office Furniture Ltd.", "NORTHERN OFFICE FURNITURE", "250000",
            "250000", "2025-09-20", "56101703", "Office desks"),
        # Services contract -> must NOT appear in goods leaderboard.
        _ch("C-005", "000", "Big Consulting LLP", "BIG CONSULTING", "900000", "900000",
            "2025-01-05", "80101500", "Management consulting", cat="*SRV"),
        # Foreign supplier -> excluded from leaderboard.
        _ch("C-006", "000", "Shenzhen Gloves Co., Ltd.", "SHENZHEN GLOVES", "10000", "10000",
            "2025-04-04", "46181504", "Protective gloves", city="Shenzhen", prov="", country="China"),
        # Multi-line supplier field (seen in real files) -> first line used.
        _ch("C-007", "000", "Northern Office Furniture Ltd.\nSecond Name Inc.", "NORTHERN OFFICE FURNITURE",
            "40000", "40000", "2022-05-05", "56101703", "Office desks"),
    ]
    _write(raw / "contract_history_current.csv", CH, ch)

    an = [  # C-001 duplicates contract history (dropped); C-900 only exists here (kept).
        dict(contractNumber="C-001", amendmentNumber="000", contractAwardDate="2025-03-01",
             supplierLegalName="Acme Safety Supply Inc.", contractAmount="100000", procurementCategory="*GD",
             unspsc="46181504", contractingEntityName="PSPC"),
        dict(contractNumber="C-900", amendmentNumber="000", contractAwardDate="2025-08-08",
             supplierLegalName="Maple Lighting Corp", contractAmount="75000", procurementCategory="*GD",
             unspsc="39111500", unspscDescription="Lighting fixtures", contractingEntityName="Parks Canada",
             supplierAddressCountry="Canada"),
    ]
    _write(raw / "award_notices_current.csv", AN, an)

    tn = [
        dict(solicitationNumber="T-1", amendmentNumber="0", title="Supply of work gloves", tenderStatus="Open",
             procurementCategory="*GD", unspsc="46181504", unspscDescription="Protective gloves",
             contractingEntityName="Correctional Service Canada", publicationDate="2026-10-01",
             tenderClosingDate="2099-01-01T14:00:00", noticeURL="https://canadabuys.canada.ca/x"),
        dict(solicitationNumber="T-1", amendmentNumber="1", title="Supply of work gloves (amended)",
             tenderStatus="Open", procurementCategory="*GD", unspsc="46181504",
             contractingEntityName="Correctional Service Canada", publicationDate="2026-10-05",
             tenderClosingDate="2099-01-01T14:00:00"),
        dict(solicitationNumber="T-2", title="Audit services", tenderStatus="Open", procurementCategory="*SRV",
             unspsc="84111600", tenderClosingDate="2099-01-01T14:00:00"),
        dict(solicitationNumber="T-3", title="Expired desks", tenderStatus="Expired", procurementCategory="*GD",
             unspsc="56101703", tenderClosingDate="2020-01-01T14:00:00"),
    ]
    _write(raw / "tenders_open.csv", TN, tn)
