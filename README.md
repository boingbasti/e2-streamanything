# StreamAnything

Enigma2-Plugin zum Verwalten und Abspielen eigener Streams auf VU+ und anderen Enigma2-Boxen.  
Vollständig per WebIF im Browser bedienbar – keine Fernbedienung nötig.

## Features

- **Streams und Ordner** – Streams können frei in Ordnern organisiert werden, im Plugin als Stream oder Ordner gekennzeichnet
- **Kachelansicht** – übersichtliche 4×3-Kachelnavigation mit Logo, Name und Typ-Icon
- **Listenansicht** – kompakte Listenansicht mit Logo, Name und Typ-Icon; umschaltbar per gelber Taste
- **Logos** – eigene Logos für Streams und Ordner hochladbar (PNG, max. 2 MB); Logo-URL wird gespeichert und beim Bearbeiten vorausgefüllt
- **Sortieren** – Einträge per Fernbedienung umsortieren (rote Taste im Plugin)
- **Stream-Einstellungen** – Player, User-Agent und HLS-Option pro Stream direkt im Plugin änderbar (Menü-Taste)
- **Streamwechsel während Wiedergabe** – mit CH+/- zum nächsten oder vorherigen Stream in der Liste wechseln
- **M3U-Import** – Playlists direkt per WebIF importieren:
  - Alle Einträge oder nur eine manuelle Auswahl übernehmen
  - Logos aus der Playlist werden automatisch heruntergeladen und gespeichert
  - Import als einzelne Streams, als neuer Ordner oder in einen vorhandenen Ordner
  - Duplikat-Check per URL: bereits vorhandene Streams werden übersprungen
- **YouTube Live** – YouTube-Livestreams werden automatisch aufgelöst (höchste verfügbare Qualität)
- **Player-Auswahl** – pro Stream wählbar: Auto, exteplayer3, gstplayer oder Standard-Player
  - **Auto** (Standard): verwendet exteplayer3 wenn ServiceApp installiert ist, sonst den Enigma2-Standard-Player
  - **exteplayer3 / gstplayer**: erzwingt den jeweiligen Player unabhängig von ServiceApp
- **User-Agent** – pro Stream einstellbarer HTTP-User-Agent (z. B. für streams mit Zugriffsbeschränkung)
- **Lokaler Playlist Server** – optionaler HLS-Fix pro Stream: lädt das Master-Manifest, wählt die beste Qualitätsstufe und übergibt dem Player eine lokale Playlist; löst Audioprobleme bei bestimmten öffentlich-rechtlichen HLS-Streams
- **ServiceApp-Auto-Konfiguration** – optimale Einstellungen für Live-Streams werden automatisch gesetzt
- **Backup/Restore** – Stream-Konfiguration exportieren und importieren:
  - **Alles ersetzen** – vorhandene Einträge werden vollständig durch das Backup ersetzt
  - **Einträge hinzufügen** – Backup wird zu den vorhandenen Einträgen hinzugefügt, Duplikate (gleiche ID) werden übersprungen
- **WebIF** – vollständige Verwaltung über den Browser, erreichbar unter `http://<Box-IP>:8090`

## Voraussetzungen

- Enigma2 / VTI (getestet auf VU+ Uno 4K SE mit VTi 15.0.04 und Python 2.7)
- **ServiceApp** (optional) – wird für exteplayer3 und GStreamer benötigt. Im Player-Modus "Auto" wird exteplayer3 verwendet, wenn ServiceApp installiert ist; andernfalls fällt der Player automatisch auf den Enigma2-Standard-Player zurück und der Stream startet trotzdem. Bei explizit erzwungenem "exteplayer3" oder "GStreamer" gibt es keinen Fallback – ohne ServiceApp startet kein Stream. Die Einstellung "ServiceApp auto-konfigurieren" hat nur Wirkung, wenn ServiceApp installiert ist.
- **Aktuelle CA-Zertifikate** (empfohlen) – VTI-Installationen haben oft veraltete CA-Zertifikate, was HTTPS-Verbindungen für YouTube-Auflösung, Logo-Download und HLS-Manifest-Abruf scheitern lassen kann. Im Release-Verzeichnis liegt ein aktuelles Paket bei, das bei Bedarf installiert werden kann:

  ```sh
  opkg install ca-certificates-mozilla_2026.05.30_all.ipk
  ```

## Installation

**Via IPK:**

IPK-Datei auf die Box kopieren und installieren:

```sh
opkg install enigma2-plugin-extensions-streamanything_1.0.0_all.ipk
```

Anschließend Enigma2 neu starten.

**Via tar (Entwickler):**

```sh
tar cf - --exclude='__pycache__' --exclude='*.pyo' --exclude='*.pyc' StreamAnything \
  | ssh root@<Box-IP> "tar xf - -C /usr/lib/enigma2/python/Plugins/Extensions/"
```

## Deinstallation

```sh
opkg remove enigma2-plugin-extensions-streamanything
```

Die Stream-Konfiguration (`/etc/enigma2/streamanything.json`) und eigene Logos (`/usr/lib/enigma2/python/Plugins/Extensions/StreamAnything/logos/`) werden dabei **nicht** automatisch gelöscht und müssen bei Bedarf manuell entfernt werden.

## Nutzung

### Plugin

Das Plugin ist im Enigma2-Hauptmenü unter **StreamAnything** erreichbar.  
Navigation mit den Pfeiltasten, Öffnen mit **OK**, Zurück mit **EXIT**.

#### Kachelansicht

Standardansicht mit 4×3 Kacheln. Seitenweise blättern mit **CH+/-**.

#### Listenansicht

Umschalten per **gelber Taste**. Navigation mit **Hoch/Runter** (einzeln, mit Wrap-Around) oder **Links/Rechts** (seitenweise). Die aktuelle Position wird unten rechts angezeigt.

#### Sortieren

**Rote Taste** aktiviert den Sortiermodus. Mit **OK** einen Eintrag greifen, mit **Hoch/Runter** verschieben, erneut **OK** zum Ablegen. In der Listenansicht verschiebt **Links/Rechts** den gegriffenen Eintrag seitenweise.

- **Grüne Taste** – Fertig: Reihenfolge speichern und Sortiermodus beenden
- **Rote Taste** – Rückgängig: alle Änderungen verwerfen und Reihenfolge wiederherstellen
- **EXIT** – bei ungespeicherten Änderungen erscheint eine Bestätigungsabfrage

#### Stream-Optionen (Menü-Taste auf einem Stream)

Die **Menü-Taste** öffnet bei einem markierten Stream einen eigenen Optionen-Screen im Plugin-Design:

| Option | Beschreibung |
|---|---|
| Player | Untermenü: Auto, exteplayer3, GStreamer oder Standard-Player |
| User-Agent | Untermenü: (keiner), Android/Chrome, Windows/Chrome, iPhone/Safari, VLC |
| Lokaler Playlist Server | Direkter Toggle EIN/AUS |
| Löschen | Stream löschen (mit Bestätigungsabfrage) |

Änderungen an Player, User-Agent und HLS-Fix bleiben zunächst ausstehend. **Grüne Taste** speichert, **Rote Taste** oder **EXIT** bricht ab – bei ungespeicherten Änderungen erscheint eine Bestätigungsabfrage.

#### Ordner-Optionen (Menü-Taste auf einem Ordner)

Die **Menü-Taste** auf einem Ordner öffnet eine Bestätigungsabfrage zum Löschen des Ordners samt aller enthaltenen Streams.

#### Einstellungen (globale Plugin-Einstellungen)

Über die **grüne Taste** erreichbar (außerhalb des Sortiermodus). Änderungen gelten erst nach dem Speichern.

- **OK** – Einstellung ändern
- **Grüne Taste** – Speichern und schließen
- **Rote Taste / EXIT** – Abbrechen; bei ungespeicherten Änderungen erscheint eine Bestätigungsabfrage

| Einstellung | Standard | Beschreibung |
|---|---|---|
| Links/Rechts zum Blättern | Ein | In der Kachelansicht wechselt Links/Rechts am ersten oder letzten Eintrag einer Seite automatisch zur vorherigen oder nächsten Seite |
| Höchste Qualität bevorzugen | Ein | Aus dem HLS-Manifest wird die beste Qualitätsstufe extrahiert und direkt an den Player übergeben |
| ServiceApp auto-konfigurieren | Ein | Setzt beim Abspielen automatisch optimale ServiceApp-Einstellungen für Live-Streams: Downmix, Autoselect Stream sowie je nach exteplayer3-Version HLS-Explorer und AAC-Software-Dekodierung |
| WebIF im Hintergrund | Ein | WebIF beim Starten des Plugins automatisch im Hintergrund starten |
| WebIF Port | 8090 | Port des WebIF (wählbar: 8080, 8088, 8090, 8181, 8888, 9000) |

#### Streamwechsel während der Wiedergabe

Während ein Stream läuft, wechseln **CH+** und **CH-** zum nächsten bzw. vorherigen Stream in der aktuellen Liste. Ordner werden dabei übersprungen. Der neue Stream startet mit seinen eigenen Einstellungen (Player, User-Agent, HLS-Fix).

### WebIF

Im Browser öffnen: `http://<Box-IP>:8090`

Über das WebIF können Streams und Ordner angelegt, bearbeitet, sortiert und gelöscht werden. Logos lassen sich direkt hochladen oder per URL laden. M3U-Playlists können über den Button **Playlist** importiert werden.

Beim Anlegen oder Bearbeiten eines Streams innerhalb eines Ordners steht der Button **Von Ordner** zur Verfügung, um das Logo des Ordners direkt zu übernehmen.

Der Port ist im Plugin unter **Einstellungen** änderbar (Standard: 8090).

## YouTube-Livestreams

YouTube-URLs (`youtube.com/watch?v=...`) werden automatisch erkannt und über die InnerTube-API aufgelöst. Es wird die höchste verfügbare HLS-Qualität gewählt.

Nur Live-Streams werden unterstützt — normale YouTube-Videos nicht.

## Lizenz

GPL2 – siehe [LICENSE](LICENSE)

YouTube-Auflösung basiert auf dem Ansatz von [Taapat/enigma2-plugin-youtube](https://github.com/Taapat/enigma2-plugin-youtube) (GPL2).
