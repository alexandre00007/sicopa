from __future__ import annotations

MANUAL_TITLE = "SICORPA - Manuel utilisateur et guide d'interpretation des annexes"
MANUAL_SUBTITLE = "Systeme Integre de Controle et de Rapprochement de la Paie"

MANUAL_SECTIONS = [
    ("1. Objectif du manuel", [
        "Ce manuel explique comment utiliser SICORPA, comment lancer les principaux traitements et surtout comment interpreter les rapports et annexes produits. Une annexe est un outil d'audit : elle doit etre lue avec son perimetre, sa periode, sa source et sa categorie d'analyse.",
        "Regle generale : un nombre de lignes n'est pas toujours un nombre d'agents. SICORPA distingue les lignes physiques, les occurrences, les repetitions, les agents uniques et les regimes distincts."
    ]),
    ("2. Demarrage et configuration", [
        "Configurer les institutions, regimes et mappings avant les imports. Pour chaque source, verifier le trimestre, l'annee, l'institution et le regime. Les imports flexibles acceptent des colonnes supplementaires ou manquantes, mais les analyses d'identite exigent des cles exploitables.",
        "Matricule et nom sont les deux informations les plus importantes pour les rapprochements. Les valeurs NU, N.U, NULL, vide, N/A, NA, NEANT, INCONNU et variantes ne doivent jamais etre interpretees comme un vrai matricule commun entre deux agents."
    ]),
    ("3. Importation et qualite des donnees", [
        "Paie Access : selectionner la table, le perimetre et lancer le chargement. Declaratif Excel : verifier la feuille, la ligne d'en-tete et le mapping avant import. Les colonnes supplementaires sont conservees lorsque le moteur flexible peut les rattacher au RAW de destination.",
        "Consulter Qualite & RAW apres import. Une source de qualite faible ou inexploitable pour le matching doit etre corrigee ou confirmee avant une analyse d'identite."
    ]),
    ("4. Rapprochement standard", [
        "Le rapprochement recherche en priorite un matricule valide, puis utilise le nom normalise lorsque le matricule n'est pas exploitable. Les filtres definissent le perimetre de travail et doivent etre verifies avant le lancement.",
        "Interpretation : PRESENT/COMMUN signifie qu'une correspondance a ete trouvee selon la cle indiquee. ABSENT indique qu'aucune correspondance exploitable n'a ete retrouvee dans le perimetre choisi. Une correspondance par nom doit etre controlee plus attentivement qu'une concordance stricte matricule + nom."
    ]),
    ("5. Comparaison regime contre regime", [
        "Cette analyse compare deux regimes sur une meme periode. Les categories communes doivent etre interpretees selon la cle utilisee : matricule, nom ou matricule + nom. Les colonnes de remuneration et de net permettent d'identifier les ecarts et les paiements potentiellement doubles.",
        "Les annexes incluent les informations complementaires disponibles : section, categorie, grade, unite d'affectation, province, institution et autres colonnes standardisees. Un ecart de nom sur un meme matricule doit etre classe comme identite a verifier et non comme correspondance certaine."
    ]),
    ("6. Comparaison RAW par periode", [
        "Cette fonction compare deux tables raw_* sur un trimestre et une annee. Les schemas peuvent etre differents : les colonnes d'identite sont prioritaires et les annexes reprennent les colonnes disponibles de chaque source.",
        "Occurrences = nombre de lignes physiques de la source correspondant a l'identite. Repetitions = occurrences - 1. Les categories communes par matricule et nom exigent une concordance stricte des deux cles apres normalisation."
    ]),
    ("7. Fusion & analyse multi-regimes", [
        "La fusion reunit plusieurs raw_* d'une meme periode pour creer une vue multi-regimes. SICORPA conserve les sources, execution_id et lignes physiques afin que chaque resultat agrege puisse etre audite.",
        "Un agent multi-regimes est une identite exploitable observee dans au moins deux regimes. Un paiement multiple meme regime correspond a plusieurs lignes physiques pour la meme identite dans un meme regime. Un matricule partage entre plusieurs noms est une anomalie d'identite : SICORPA bloque alors les conclusions automatiques fortes de double paiement ou multi-regime."
    ]),
    ("8. Annexes de Fusion & analyse multi-regimes", [
        "00_synthese.xlsx : vue generale de la fusion, periode, sources, regimes, agents et masses. Commencer l'analyse par ce fichier.",
        "01_tous_les_agents.xlsx : tous les agents agreges de la fusion. Une ligne correspond a une identite analysee, pas necessairement a une ligne physique source.",
        "02_agents_deux_regimes.xlsx : identites presentes dans exactement deux regimes.",
        "03_agents_trois_regimes_plus.xlsx : identites presentes dans trois regimes ou plus ; priorite elevee de controle.",
        "04_paiements_multiples.xlsx : identites repetees dans un meme regime. Verifier les lignes physiques, les montants et la nature des rubriques avant de conclure a un double paiement.",
        "05_identites_incoherentes_strictes.xlsx : matricules ou cles associes a des identites contradictoires. A traiter comme anomalies de referentiel, pas comme double paiement certain.",
        "06_plusieurs_institutions.xlsx : identites presentes dans plusieurs institutions. La situation peut etre legitime ou anormale selon les regles metier.",
        "07_matrice_regimes.xlsx : matrice de croisements entre regimes. Elle permet de voir combien d'identites sont partagees entre chaque paire de regimes.",
        "08_listing_fusionne_complet.xlsx : RAW fusionne exhaustif. Utiliser pour retourner aux donnees originales et verifier des colonnes non presentes dans les syntheses.",
        "09_doublons_matricule.xlsx : matricules apparaissant plusieurs fois. NU/NULL/vide ne doivent pas etre traites comme doublons de matricule valides.",
        "10_doublons_nom.xlsx : noms normalises repetes. Attention aux homonymes : une repetition de nom n'est jamais a elle seule une preuve d'identite.",
        "11_toutes_occurrences_confondues.xlsx : annexe exhaustive ligne par ligne. La feuille Synthese agents agrege les identites ; Toutes les lignes reprend chaque ligne physique ; Controle coherence verifie lignes, brut et net entre detail et agregat.",
        "12_synthese_occurrences_agents_a_risque.xlsx : annexe ciblee. Elle exclut les agents sains mono-regime et ne conserve que les cas a investiguer : multi-regimes, repetitions, doublons, identites incoherentes, matricules non exploitables ou plusieurs institutions. Les feuilles de detail reprennent les lignes physiques par type d'anomalie."
    ]),
    ("9. Comment interpreter les occurrences", [
        "Exemple : un agent apparait deux fois en Regime A et une fois en Regime B. Nombre de lignes physiques = 3 ; occurrences = 3 ; repetitions = 2 ; regimes distincts = 2. L'annexe 11 doit contenir exactement trois lignes pour cette identite.",
        "Une occurrence n'est pas automatiquement une fraude. Elle peut provenir de plusieurs rubriques, regularisations ou sources. L'interpretation doit comparer execution, regime, institution, montants, section, grade et unite d'affectation."
    ]),
    ("10. Analyse multi-regimes et analyse groupee des listings", [
        "Analyse multi-regimes travaille avec un declaratif choisi et plusieurs listings. Analyse groupee des listings fonctionne sans declaratif. Dans les deux cas, verifier les sources et leurs filtres avant lancement.",
        "Les annexes par categorie servent a isoler les cas : multi-regimes, multi-institutions, doublon matricule, doublon nom, matricule non exploitable et ligne unique. Le fichier d'effectifs uniques sert a compter les personnes, tandis que le detail global sert a auditer les lignes."
    ]),
    ("11. Console SQL", [
        "La Console SQL est destinee a la lecture et a l'analyse des tables disponibles. Utiliser les modeles SELECT, JOIN, LEFT JOIN et les autres operations proposees. L'affichage peut etre pagine ou limite, mais l'export est exhaustif.",
        "Excel est adapte aux analyses humaines ; CSV est pratique pour les echanges ; Parquet est recommande pour les tres gros volumes."
    ]),
    ("12. Exports et limites Excel", [
        "Les exports volumineux sont ecrits en streaming. Lorsqu'une feuille depasse la limite Excel, SICORPA cree automatiquement des feuilles suffixees _2, _3, etc. Une limite d'affichage dans l'interface ne doit pas etre confondue avec une limite d'export.",
        "Toujours conserver le dossier complet d'un traitement avec sa synthese et ses annexes. Ne pas interpreter une annexe isolee sans son identifiant de traitement, sa periode et son contexte."
    ]),
    ("13. Reanalyse et versions", [
        "La reanalyse recalcule les classifications a partir des lignes sources conservees. Les lignes physiques ne doivent pas disparaitre lors d'une reanalyse ; seuls les diagnostics ou classifications peuvent evoluer si les regles changent.",
        "Comparer les versions lorsqu'une conclusion change. Utiliser les historiques de campagne, fusion ou analyse pour tracer les traitements successifs."
    ]),
    ("14. Lecture des anomalies", [
        "MATRICULE_PARTAGE_IDENTITES_DIFFERENTES : meme matricule, plusieurs noms normalises. Controle manuel obligatoire.",
        "DOUBLON_MATRICULE : matricule valide repete. Examiner regime, institution, lignes source et montants.",
        "DOUBLON_NOM : nom repete. Risque d'homonymie ; ne pas conclure sans autre cle.",
        "PAIEMENT_MULTIPLE_MEME_REGIME : plusieurs lignes d'une meme identite dans un regime. Verifier si elles correspondent a plusieurs paiements ou a des composantes legitimes.",
        "MULTI_REGIME / DEUX_REGIMES / TROIS_REGIMES_OU_PLUS : meme identite retrouvee dans plusieurs regimes. Prioriser les cas avec masses importantes et concordance forte matricule + nom.",
        "MATRICULE_NU / NULL / VIDE / NON_EXPLOITABLE : absence de cle matricule fiable. L'analyse doit alors s'appuyer sur le nom et les informations annexes, avec prudence."
    ]),
    ("15. Methode de controle recommandee", [
        "1) Verifier la periode et les sources. 2) Lire la synthese. 3) Identifier les categories a risque. 4) Ouvrir l'annexe detaillee. 5) Comparer les lignes physiques. 6) Verifier matricule, nom, regime, institution, affectation et montants. 7) Retourner au RAW complet si necessaire. 8) Documenter la conclusion metier.",
        "Une alerte SICORPA est un signal de controle. La decision finale doit tenir compte des regles administratives, des justificatifs et du contexte de paie."
    ]),
    ("16. Sante, maintenance et diagnostic", [
        "L'onglet Sante & Maintenance affiche l'etat DuckDB, la taille de la base, les temporaires, les traitements et erreurs recentes. Utiliser CHECKPOINT et le rafraichissement du catalogue selon les besoins.",
        "En cas d'erreur, conserver la reference SIC-..., l'operation, les details techniques et le journal sicorpa.log. Utiliser Aide > Diagnostic pour verifier DuckDB, espace disque, pilote Access et OCR."
    ]),
]

QUICK_GUIDE_ADDENDUM = """

13. FUSION & ANALYSE MULTI-REGIMES - ANNEXES D'AUDIT
L'export complet comprend maintenant deux annexes d'occurrences complementaires. L'annexe 11 montre toutes les lignes physiques ayant servi a la fusion, y compris les cas sains. L'annexe 12 est reservee aux agents a risque et exclut les agents mono-regime sans anomalie.

Annexe 11 - Toutes occurrences confondues : utilisez la feuille Synthese agents pour les totaux par identite, Toutes les lignes pour remonter ligne par ligne aux sources, et Controle coherence pour verifier que les nombres de lignes, brut et net correspondent aux agregats.

Annexe 12 - Synthese occurrences agents a risque : commencez par Synthese generale, puis ouvrez les feuilles Detail par matricule, Detail par nom, Matricule + nom, NU, NULL/vide, identites incoherentes, multi-regimes, paiements multiples et plusieurs institutions selon le cas. Un agent sain mono-regime ne doit pas apparaitre dans cette annexe.

Pour une interpretation complete, utilisez Aide > Mode d'emploi puis le bouton Manuel PDF complet.
"""
