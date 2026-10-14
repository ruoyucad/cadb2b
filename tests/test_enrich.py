from cbintel.enrich import guess_domains, score_site, verified, ROLE_EMAIL, NOT_COMPANY_SITES

NITAM = {"supplier_key": "NITAM SOLUTIONS", "city": "Ottawa", "province": "Ontario", "postal_code": "K1G 3N3"}
ASOKAN = {"supplier_key": "ASOKAN BUSINESS INTERIORS", "city": "Gatineau", "province": "QC", "postal_code": "J8Z 1V8"}


def test_guess_domains():
    assert {"nitamsolutions.ca", "nitam.ca", "nitam.com"} <= set(guess_domains("NITAM SOLUTIONS"))


def test_company_site_verified():
    text = "Nitam Solutions Inc. — 1234 Some Rd, Ottawa ON K1G 3N3 — 613-555-0100"
    _, why = score_site(text, "nitam.ca", NITAM)
    assert verified(why) and "postal code" in why


def test_directory_page_rejected():
    # A directory lists the same name and postal code, but its domain isn't the company's.
    text = "Nitam Solutions Inc. Ottawa ON K1G 3N3"
    _, why = score_site(text, "local.infobel.ca", NITAM)
    assert not verified(why)


def test_one_word_name_needs_more_evidence():
    # asokan.com is an unrelated real-estate team: name token in the domain, nothing else.
    _, why = score_site("Asokan Real Estate Team", "asokan.com", ASOKAN)
    assert not verified(why)
    # The real site has a Gatineau (819) phone number.
    _, why = score_site("ASOKAN | Solution de bureau, mobilier. 819-772-1001", "asokangroup.ca", ASOKAN)
    assert verified(why) and "area code" in why


def test_role_emails_only():
    assert ROLE_EMAIL.match("info@asokangroup.ca") and ROLE_EMAIL.match("customercare@nitam.ca")
    assert not ROLE_EMAIL.match("francois@nitam.ca")


def test_directories_blocked():
    assert NOT_COMPANY_SITES.search("www.yellowpages.ca") and NOT_COMPANY_SITES.search("ca.linkedin.com")
    assert not NOT_COMPANY_SITES.search("nitam.ca")
