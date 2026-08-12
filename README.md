# SICORPA

**Système Intégré de Contrôle et de Rapprochement de la Paie**  
Version 1.0.0 — Développé par **Alexandre Mulumba Kande**.

SICORPA est une application locale Tkinter utilisant DuckDB comme base analytique centrale. Elle importe les listings Access et les déclaratifs Excel, applique des filtres métier, rapproche les agents, détecte les anomalies et produit le rapport final, la lettre d’interprétation destinée à l’institution, les annexes détaillées et les effectifs uniques.

## Affichage

La fenêtre principale démarre maximisée. Les dialogues sont automatiquement centrés et limités à l’espace visible de l’écran. Les formulaires secondaires utilisent un défilement vertical et conservent leurs boutons d’action visibles.

## Utilisation

1. Configurez les institutions, régimes et mappings de colonnes.
2. Importez la table de paie Access.
3. Importez le déclaratif Excel du même périmètre.
4. Configurez ou simulez les formules dans **Calculs financiers**. Les formules sont versionnées par institution, régime, rubrique et date d’effet.
5. Définissez les filtres du listing.
6. Lancez le rapprochement et générez le rapport. SICORPA place automatiquement `lettre_interpretation.docx` à côté de `rapport_final.xlsx`.

Le menu **Outils fichiers** fournit aussi trois utilitaires autonomes :

- rotation d’un PDF de 90°, 180° ou 270° ;
- conversion d’un PDF numérique en Excel ;
- conversion d’un PDF numérique en Word.

Les conversions extraient le texte et les tableaux détectables. L’OCR automatique intégré reconnaît aussi les pages scannées en français, en anglais ou dans les deux langues. Tesseract OCR doit être installé sur la machine et son état est visible dans **Aide > Diagnostic**.

Le mode d’emploi complet est accessible dans **Aide > Mode d’emploi**.

## Données persistantes

SICORPA ne stocke jamais la base dans l’exécutable. Au premier démarrage, les dossiers sont créés automatiquement.

Sous Windows :

- base : `%LOCALAPPDATA%\SICORPA\controle_paie.duckdb`;
- journaux : `%LOCALAPPDATA%\SICORPA\journaux`;
- résultats : `Documents\SICORPA\Resultats`;
- sauvegardes : `Documents\SICORPA\Sauvegardes`.

Sous Linux :

- base : `~/.local/share/sicorpa/controle_paie.duckdb`;
- résultats et sauvegardes : `~/Documents/SICORPA/`.

Si `traitement/controle_paie.duckdb` existe encore au premier lancement, il est copié vers le nouvel emplacement sans supprimer l’original. Une sauvegarde est créée avant les migrations.

Pour imposer un dossier portable ou de test, définissez la variable `SICORPA_HOME`.

## Lancement depuis les sources

Python 3.10 ou supérieur :

```bash
python -m pip install -r requirements.txt
python app.py
```

## Construction d’une version d’essai

La durée est injectée pendant la compilation et le compteur commence au premier lancement de l’exécutable.

Linux, pour un essai de 30 jours :

```bash
./build_linux.sh 30
```

Windows :

```bat
build_windows.bat 30
```

Sans argument, le script demande la durée et propose 30 jours. Le fichier .sicorpa_trial_secret est créé localement : conservez-en une sauvegarde sécurisée pour que les futures constructions reconnaissent le même état d’essai. Ce fichier et la configuration générée ne doivent jamais être publiés sur GitHub.

Après expiration ou recul anormal de plus de six heures, les nouveaux imports, rapprochements, rapports et traitements PDF sont bloqués. Les données existantes restent consultables, exportables et sauvegardables.

## Construction Windows

La compilation Windows doit être exécutée sous Windows :

```bat
build_windows.bat
```

Le résultat est `dist\SICORPA.exe`. L’exécutable peut être déplacé; la base reste dans le profil utilisateur et survit aux mises à jour.

## Construction Linux

```bash
chmod +x build_linux.sh
./build_linux.sh
```

## OCR des PDF scannés

L’OCR utilise Tesseract sans connexion Internet. Sous Linux, installez tesseract-ocr et tesseract-ocr-fra. Sous Windows, installez Tesseract OCR avec les données linguistiques française et anglaise. Le menu **Aide > Diagnostic** affiche le moteur détecté.

## Lecture Access

- Windows : installez le pilote ODBC Microsoft Access correspondant à l’architecture de l’exécutable.
- Linux : installez `mdbtools` (`sudo apt-get install -y mdbtools`).

Le menu **Aide > Diagnostic** contrôle DuckDB, les dossiers, l’espace disque et le lecteur Access.
