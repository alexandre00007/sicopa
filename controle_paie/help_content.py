USER_GUIDE = """SICORPA — MODE D’EMPLOI

ERGONOMIE DES FENÊTRES
La fenêtre principale démarre maximisée. Les fenêtres secondaires sont centrées et adaptées à la résolution de l’écran. Lorsque leur contenu dépasse la hauteur disponible, utilisez la barre de défilement ou la molette; les boutons d’action restent visibles en bas.

1. CONFIGURATION INITIALE
Ajoutez les institutions et les régimes dans l’onglet Configuration. Dans Mapping colonnes, utilisez ACCESS pour une table Access, PAIE_EXCEL pour un listing de paie Excel et EXCEL pour le déclaratif. Associez les colonnes du fichier aux champs standards et rendez obligatoires celles qui sont indispensables au contrôle.

2. IMPORTATION DU LISTING DE PAIE
Choisissez l’institution, le régime, le trimestre et l’année. Dans Paie, sélectionnez Base Access ou Listing Excel. Pour Access, choisissez le fichier .mdb/.accdb puis cliquez d’abord sur Lister les tables. Sous Windows, SICORPA vérifie le pilote avant la connexion et choisit automatiquement un pilote Access compatible. L’erreur IM002 signifie que Microsoft Access Database Engine est absent, mal enregistré ou d’une architecture différente : installez la même architecture 32/64 bits que SICORPA puis redémarrez Windows. Sous Linux, mdbtools est requis. Pour Excel, choisissez le classeur, la feuille et la ligne d’en-tête, puis affichez l’aperçu. La liste des champs standards acceptés reste visible dans l’onglet. Une fenêtre de progression présente la lecture, le nombre de lignes, la standardisation et l’écriture dans DuckDB.

3. IMPORTATION DU DÉCLARATIF EXCEL
Choisissez le même périmètre. Le chargeur suit quatre étapes : fichier, feuille, ligne d’en-tête et mode d’importation. Cliquez sur Analyser la structure : l’onglet Structure d’importation indique en permanence chaque champ standard, son type, la colonne Excel reconnue et son état. Matricule et Nom / noms de l’agent sont tous les deux obligatoires : ils doivent être mappés et contenir au moins une valeur exploitable. Une croix rouge et un avertissement bloquent le chargement si l’un manque. Utilisez Ajouter une nouvelle version pour conserver l’historique; Remplacer le périmètre est refusé lorsque le déclaratif actuel alimente déjà des résultats.

Dans Historique et suppression, SICORPA présente les imports du périmètre sélectionné. Un import libre peut être supprimé de DuckDB après confirmation; le fichier Excel d’origine reste intact et le journal conserve la trace. Un import utilisé par un rapprochement ou une campagne multi-régimes ne peut pas être supprimé.

4. FILTRAGE DU LISTING
Dans Rapprochement, choisissez une colonne standardisée, un opérateur et un contenu. Plusieurs filtres sont combinés avec ET. Le bouton Vérifier le périmètre indique le nombre de lignes retenues.

5. RAPPROCHEMENT
Le matricule valide est prioritaire, puis le nom normalisé. NU, N.U et leurs variantes sont considérés comme non exploitables et ne créent jamais de doublons de matricule.
Dans Calcul de l’impact, conservez Automatique par régime et rubrique pour appliquer les versions actives correspondant au périmètre. Le mode Forcer une formule globale permet de choisir explicitement une formule configurée avec la rubrique « * »; cette version est alors utilisée pour toutes les catégories du rapprochement, du rapport et des annexes. SICORPA refuse une formule inactive, future ou appartenant à un autre régime ou à une autre institution.

5 BIS. ANALYSE MULTI-RÉGIMES
Dans Rapprochement, ouvrez Analyse multi-régimes. Choisissez l’institution, le régime et la période, puis cliquez sur Rechercher les données. Sélectionnez obligatoirement une version précise du déclaratif; SICORPA ne mélange jamais deux imports déclaratifs. Sélectionnez ensuite les listings par double-clic ou avec les boutons de sélection.

Cliquez sur Aperçu après filtres existants. Le tableau affiche pour chaque source les lignes retenues, les filtres, la formule d’impact, le type de mapping et les anomalies éventuelles. Voir un échantillon montre les premières lignes réellement retenues. Le lancement est bloqué si une source ne contient aucune ligne ou aucun identifiant exploitable.

Avant le traitement, une confirmation récapitule le déclaratif, les sources, les régimes et les effectifs. La base de campagne provient de la paie standardisée et ne modifie jamais les raw_*. L’impact dépend du régime et de l’institution de paiement. Historique des campagnes permet de recharger, réexporter, ouvrir le dossier ou archiver une campagne. L’export contient le rapport, le détail global, une annexe par catégorie, l’effectif unique et la lettre d’interprétation.

5 TER. ANALYSE GROUPÉE DES LISTINGS
Dans Rapprochement, ouvrez Analyse groupée des listings lorsqu’aucune liste déclarative ne doit intervenir. Donnez un nom au groupe, choisissez une période commune et recherchez les listings. Sélectionnez ou désélectionnez librement les sources; chaque source conserve les filtres configurés pour son institution et son régime.

Vérifier le groupe affiche les effectifs avant et après filtres et bloque les sources vides ou sans identifiant exploitable. Constituer la base et analyser crée une photographie indépendante dans DuckDB sans modifier les tables raw_* ni les imports d’origine. Chaque ligne reçoit une seule catégorie, selon la priorité suivante : matricule non exploitable, paiement dans plusieurs régimes, paiement dans plusieurs institutions, doublon de matricule, doublon de nom, puis ligne unique.

L’impact potentiel est calculé avec la formule correspondant à l’institution et au régime de chaque ligne source. L’export progressif génère un rapport de synthèse, une annexe globale, une annexe par catégorie, un fichier d’effectifs uniques et une lettre d’interprétation. Historique permet de recharger, réexporter, ouvrir le dossier ou archiver un groupe.

6. AGENTS PAYÉS HORS PÉRIMÈTRE
La cohorte contient les agents du déclaratif présents dans le listing filtré. Elle est recherchée dans tout le listing du trimestre hors périmètre filtré, y compris dans une autre section de la même institution.

7. RAPPORT ET ANNEXES
Le rapport final présente le listing, le déclaratif et les comparaisons. Enregistrements désigne le nombre de lignes; Nombre de concernés désigne l’effectif unique. Chaque rubrique fournit un lien vers le détail et un lien vers l’effectif unique.

8. CALCULS FINANCIERS ET IMPACT
Dans l’onglet Calculs financiers, choisissez d’abord l’institution éventuelle, le régime et la période. SICORPA détecte alors les champs financiers réellement disponibles : un champ est proposé lorsqu’il est mappé ou lorsqu’un montant non nul est observé dans la paie standardisée. Choisissez un champ, son signe et son coefficient, puis ajoutez-le à la formule.

Définissez ensuite la rubrique, la date d’entrée en vigueur et l’agrégation. La rubrique « * » crée une formule globale qui peut être choisie directement pendant le rapprochement. Utilisez Simuler avant d’enregistrer. Une nouvelle version ne modifie pas les résultats déjà calculés. L’impact potentiel doit être confirmé par un contrôle métier avant d’être considéré comme définitif.

9. OUTILS FICHIERS
Le menu Outils fichiers permet de faire pivoter toutes les pages d’un PDF de 90°, 180° ou 270°, de convertir un PDF en classeur Excel structuré et de convertir son texte et ses tableaux en document Word modifiable. Pour une page scannée, activez l’OCR automatique et choisissez Français + anglais, Français ou Anglais. Le traitement s’exécute en arrière-plan avec une progression page par page. Aide > Diagnostic indique si Tesseract OCR est disponible.

9 BIS. PERFORMANCE ET RÈGLES D’INTERFACE
SICORPA règle automatiquement DuckDB selon les processeurs et la mémoire actuellement disponibles, tout en conservant une réserve pour Windows, Tkinter et la génération Excel. Aide > Diagnostic affiche le nombre de threads, la mémoire maximale et le dossier temporaire utilisés. Les administrateurs peuvent imposer des valeurs avec SICORPA_DUCKDB_THREADS et SICORPA_DUCKDB_MEMORY_MB.

Pendant un traitement, la navigation principale est temporairement verrouillée, un curseur d’attente et une progression restent visibles et la fermeture de l’application est protégée. La navigation est réactivée en cas de succès ou d’erreur. Les périmètres proposent par défaut la première institution disponible, le premier régime configuré et la période courante; l’utilisateur garde la possibilité de les modifier avant toute opération.

10. VERSION D’ESSAI
La durée est définie lors de la construction de l’exécutable et commence au premier lancement. L’en-tête et Aide > État de la version d’essai indiquent les jours restants. SICORPA mémorise le dernier lancement en UTC et bloque les nouveaux traitements si l’horloge recule anormalement ou si l’essai expire. Une correction inférieure à six heures est tolérée. La consultation, l’export et la sauvegarde des données existantes restent disponibles; aucune donnée n’est supprimée.

11. SAUVEGARDE
Utilisez Fichier > Sauvegarder la base. SICORPA crée aussi une sauvegarde avant les migrations. Les mises à jour ne doivent pas écraser la base utilisateur.

12. EN CAS D’ERREUR
La fenêtre d’erreur indique l’opération interrompue, la cause probable et les actions recommandées. Utilisez Copier le diagnostic pour transmettre la référence SIC-…, le message technique et la trace au support. Le bouton Ouvrir le journal donne accès à sicorpa.log lorsqu’il existe. Consultez également Aide > Diagnostic pour vérifier DuckDB, la mémoire, l’espace disque, le pilote Access et l’OCR.
"""
