# SICORPA

**Système Intégré de Contrôle et de Rapprochement de la Paie**  
Version 1.0.0 — Développé par **Alexandre Mulumba Kande**.

SICORPA est une application locale Tkinter utilisant DuckDB comme base analytique centrale. Elle importe les listings Access et les déclaratifs Excel, applique des filtres métier, rapproche les agents, détecte les anomalies et produit le rapport final, les annexes détaillées et les effectifs uniques.

## Utilisation

1. Configurez les institutions, régimes et mappings de colonnes.
2. Importez la table de paie Access.
3. Importez le déclaratif Excel du même périmètre.
4. Définissez les filtres du listing.
5. Lancez le rapprochement et générez le rapport.

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

## Lecture Access

- Windows : installez le pilote ODBC Microsoft Access correspondant à l’architecture de l’exécutable.
- Linux : installez `mdbtools` (`sudo apt-get install -y mdbtools`).

Le menu **Aide > Diagnostic** contrôle DuckDB, les dossiers, l’espace disque et le lecteur Access.
