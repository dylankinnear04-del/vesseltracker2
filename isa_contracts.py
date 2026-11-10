"""
ISA exploration contracts: the public ArcGIS service the map and the priority scores read live,
and who holds each contract. Nothing from the service is stored (ISA terms forbid republishing).
"""

ISA_SERVICE = ("https://services5.arcgis.com/VcAAb5oBhdAAnFj2/arcgis/rest/services/"
               "fclContractAreas_20240724/FeatureServer")
ISA_LAYERS = {"active": 32, "reserved": 33, "relinquished": 34, "apei": 35}
CCZ_OUTLINE = ("https://geo.vliz.be/geoserver/MarineRegions/wfs?service=WFS&version=1.0.0"
               "&request=GetFeature&typeName=MarineRegions:isa_ccz_managementarea"
               "&outputFormat=application/json")

# ContractID -> (contractor, sponsoring state), from the ISA's per-contractor layers
ISA_CONTRACTORS = {
    "UKSRLPMN1": ("Loke CCZ (formerly UK Seabed Resources)", "United Kingdom"),
    "UKSRLPMN2": ("Loke CCZ (formerly UK Seabed Resources)", "United Kingdom"),
    "CIICPMN1": ("Cook Islands Investment Corporation (CIIC)", "Cook Islands"),
    "COMRAPMN1": ("China Ocean Mineral Resources R&D Association (COMRA)", "China"),
    "COMRAPMS1": ("China Ocean Mineral Resources R&D Association (COMRA)", "China"),
    "COMRACRFC1": ("China Ocean Mineral Resources R&D Association (COMRA)", "China"),
    "BPHDCPMN1": ("Beijing Pioneer Hi-Tech Development Corporation", "China"),
    "CMMPMN1": ("China Minmetals Corporation", "China"),
    "BrazilCRFC1": ("Companhia de Pesquisa de Recursos Minerais (CPRM)", "Brazil"),
    "IOMPMN1": ("Interoceanmetal Joint Organization (IOM)",
                "Bulgaria, Cuba, Czechia, Poland, Russia, Slovakia"),
    "POLPMS1": ("Government of the Republic of Poland", "Poland"),
    "BMJPMN1": ("Blue Minerals Jamaica Ltd", "Jamaica"),
    "GSRPMN1": ("Global Sea Mineral Resources NV (GSR)", "Belgium"),
    "IFREMERPMN1": ("IFREMER", "France"), "IFREMERPMS1": ("IFREMER", "France"),
    "KOREAPMN1": ("Government of the Republic of Korea", "South Korea"),
    "KOREAPMS1": ("Government of the Republic of Korea", "South Korea"),
    "KOREACRFC1": ("Government of the Republic of Korea", "South Korea"),
    "OMSPMN1": ("Ocean Mineral Singapore Pte Ltd", "Singapore"),
    "RUSFEDPMS1": ("Government of the Russian Federation", "Russia"),
    "RUSMNRCRFC1": ("Ministry of Natural Resources and Environment of Russia", "Russia"),
    "RUSMNCRFC1": ("Ministry of Natural Resources and Environment of Russia", "Russia"),
    "YUZHPMN1": ("JSC Yuzhmorgeologiya", "Russia"),
    "TOMLPMN1": ("Tonga Offshore Mining Limited", "Tonga"),
    "NORIPMN1": ("Nauru Ocean Resources Inc. (NORI)", "Nauru"),
    "MARAWAPMN1": ("Marawa Research and Exploration Ltd", "Kiribati"),
    "JOGMECCRFC1": ("Japan Organization for Metals and Energy Security (JOGMEC)", "Japan"),
    "DORDPMN1": ("Deep Ocean Resources Development Co. (DORD)", "Japan"),
    "IndiaPMN1": ("Government of India", "India"), "IndiaPMS1": ("Government of India", "India"),
    "BGRPMN1": ("Federal Institute for Geosciences and Natural Resources (BGR)", "Germany"),
    "BGRPMS1": ("Federal Institute for Geosciences and Natural Resources (BGR)", "Germany"),
}


def mineral_of(contract_id: str) -> str:
    """nodules / sulphides / crusts from an ISA ContractID (as the map colours them)."""
    c = str(contract_id or "").upper()
    return "crusts" if "CRFC" in c else "sulphides" if "PMS" in c else "nodules"
