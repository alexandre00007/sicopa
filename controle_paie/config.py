from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .runtime import RuntimePaths, default_runtime_paths


FINANCIAL_TARGETS = [
    "remuneration_base", "transport", "prime", "logement",
    "pension_rente", "autres_remunerations", "retenues", "montant_net",
]


@dataclass
class RegimeConfig:
    code: str
    table_pattern: str
    raw_table: str
    mapping: Dict[str, str] = field(default_factory=dict)
    financial_components: Dict[str, List[str]] = field(default_factory=dict)


DEFAULT_REGIMES: Dict[str, RegimeConfig] = {
    "AUTRES_REGIMES": RegimeConfig("AUTRES_REGIMES", r"^Tab_AutresRegimes_T[1-4]_\d{4}$", "raw_autres_regimes"),
    "FARDC": RegimeConfig("FARDC", r"^Tab_FARDC_T[1-4]_\d{4}$", "raw_fardc"),
    "INSTITUTIONS_POLITIQUES": RegimeConfig("INSTITUTIONS_POLITIQUES", r"^Tab_InstitutionsPolitiques_T[1-4]_\d{4}$", "raw_institutions_politiques"),
    "PNC": RegimeConfig("PNC", r"^Tab_PNC_T[1-4]_\d{4}$", "raw_pnc"),
    "SECOPE_FF": RegimeConfig("SECOPE_FF", r"^Tab_SECOPE_FF_T[1-4]_\d{4}$", "raw_secope_ff"),
    "SECOPE": RegimeConfig("SECOPE", r"^Tab_SECOPE_T[1-4]_\d{4}$", "raw_secope"),
}


CANONICAL_ALIASES: Dict[str, List[str]] = {
    "matricule_source": ["Matricule", "matricule", "NumMatricule", "NumeroMatricule", "MatriculeMilitaire"],
    "nom": ["NomPostnom", "Noms", "noms", "NomComplet", "Nom"],
    "prenom": ["Prenom", "Prénom", "prenom"],
    "section": ["Section", "section"],
    "categorie": ["Categorie", "Catégorie", "categorie"],
    "grade": ["Grade", "grade"],
    "unite_affectation": ["UniteAffectation", "UnitéAffectation", "Service", "service"],
    "province": ["Province", "province"],
    "remuneration_base": ["Base", "SalaireBase", "TraitementBase", "SoldeBase"],
    "transport": ["Transport", "IndemniteTransport"],
    "prime": ["Prime", "Primes", "PrimeFonction", "PrimeMilitaire"],
    "logement": ["Logement", "IndemniteLogement"],
    "pension_rente": ["Pension_Rente", "PensionRente"],
    "retenues": ["Retenue", "Retenues"],
    "montant_net": ["MontantNet", "NetAPayer", "SoldeNette"],
}


@dataclass
class AppConfig:
    database_path: Optional[Path] = None
    results_dir: Optional[Path] = None
    backups_dir: Optional[Path] = None
    logs_dir: Optional[Path] = None
    regimes: Dict[str, RegimeConfig] = field(default_factory=lambda: dict(DEFAULT_REGIMES))
    access_driver: str = "Microsoft Access Driver (*.mdb, *.accdb)"
    runtime_paths: RuntimePaths = field(default_factory=default_runtime_paths, repr=False)

    def __post_init__(self) -> None:
        self.database_path = Path(self.database_path) if self.database_path else self.runtime_paths.database
        self.results_dir = Path(self.results_dir) if self.results_dir else self.runtime_paths.results_dir
        self.backups_dir = Path(self.backups_dir) if self.backups_dir else self.runtime_paths.backups_dir
        self.logs_dir = Path(self.logs_dir) if self.logs_dir else self.runtime_paths.logs_dir

    def add_regime(self, code: str, label: str, table_pattern: str, raw_table: str, active: bool = True) -> RegimeConfig:
        """Register a regime in the in-memory config and validate its table pattern."""
        import re

        normalized_code = code.strip().upper()
        normalized_label = label.strip()
        normalized_raw = raw_table.strip().lower()
        if not normalized_code:
            raise ValueError("Le code du régime est obligatoire.")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", normalized_code):
            raise ValueError("Le code du régime doit contenir uniquement lettres, chiffres et underscores.")
        if not normalized_label:
            raise ValueError("Le libellé du régime est obligatoire.")
        if not normalized_raw:
            raise ValueError("La table RAW du régime est obligatoire.")
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", normalized_raw):
            raise ValueError("La table RAW doit être un identifiant DuckDB valide.")
        try:
            re.compile(table_pattern)
        except re.error as exc:
            raise ValueError(f"Motif de table invalide : {exc}") from exc

        regime = RegimeConfig(normalized_code, table_pattern.strip(), normalized_raw)
        self.regimes[normalized_code] = regime
        return regime

    def detect_regime(self, table_name: str) -> Optional[str]:
        import re
        for code, config in self.regimes.items():
            if re.fullmatch(config.table_pattern, table_name, re.IGNORECASE):
                return code
        return None

    @staticmethod
    def detect_period(table_name: str) -> tuple[Optional[str], Optional[int]]:
        import re
        match = re.search(r"_(T[1-4])_(\d{4})$", table_name, re.IGNORECASE)
        return (match.group(1).upper(), int(match.group(2))) if match else (None, None)
