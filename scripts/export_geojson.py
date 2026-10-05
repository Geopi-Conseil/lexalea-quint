"""
Export des données QGIS vers les GeoJSON utilisés par la webmap.

À exécuter dans la console Python de QGIS (ou via un script PyQGIS externe
avec un environnement QGIS), depuis le projet source
`quintfonsegrives_ppri.qgz` contenant les couches enrichies :
  - "Batiments BD TOPO Quint-Fonsegrives"  -> champs zoneCode, zoneLabel,
    zoneColor, regime, zoneRefuge, refugeCategorie, diagnostic,
    eligibiliteFprnm, etudeGeotechniqueG2, etagePresent, etageSource,
    typologie, typologieSource, hauteurM, altitudeSolLidarHdM,
    coteReferencePheM, coteReferenceMethode, distanceIsocoteM,
    hauteurEauEstimeeM, hauteurEauNote
    (typologieSource distingue les bâtiments dont la typologie/étages ont
    été complétés via la BDNB, cf. docs/METHODOLOGIE.md §10, des autres,
    dérivés directement de BD TOPO®)
  - "Zonage PPRi Quint-Fonsegrives" -> champs zoneCode, zoneLabel, zoneColor,
    codeZone, typeReg, libelleZone
  - "Hauteur d'eau - polygones (classes)" -> champs classe, classeLabel,
    classeColor (voir docs/METHODOLOGIE.md §8)

Il n'existe pas de couche ERP pour cette commune à ce jour (voir faq.html) :
`erp.geojson` est exporté vide.

Produit 5 fichiers dans data/ :
  - batiments_ppri.geojson        (bâtiments touchés par le zonage, détaillés)
  - batiments_hors_zone.geojson   (autres bâtiments, géométrie + id seulement)
  - zonage_pprin.geojson
  - erp.geojson                   (vide pour cette commune)
  - hauteur_eau.geojson           (polygones classés de hauteur d'eau estimée)

Toute évolution du schéma de champs doit être répercutée dans :
  - src/js/app.js (fonction renderBuildingPanel)
  - docs/METHODOLOGIE.md (dictionnaire des champs)
"""

import json
import os
import re

from qgis.core import (
    NULL,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
)

# ---------------------------------------------------------------------------
# Configuration : adapter les noms de couches si besoin
# ---------------------------------------------------------------------------

LAYER_BATI = "Batiments BD TOPO Quint-Fonsegrives"
LAYER_ZONAGE = "Zonage PPRi Quint-Fonsegrives"
LAYER_HAUTEUR_EAU = "Hauteur d'eau - polygones (classes)"
# Pas de couche ERP pour cette commune à ce jour (voir faq.html) : erp.geojson
# est exporté vide par export_erp() ci-dessous, sans lecture de couche.

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

ZONE_COLORS = {
    "Bi": "#4FA8E0",
    "Ji": "#FBC02D",
    "Ri": "#E2001A",
    "GHi": "#8A8A8A",
    "Pi": "#9E9E9E",
}

ZONE_LABELS = {
    "Bi": "Bleue inondation",
    "Ji": "Jaune inondation (expansion des crues)",
    "Ri": "Rouge inondation",
    "GHi": "Grise hachurée inondation (crue historique)",
    "Pi": "Pi",
}

# ---------------------------------------------------------------------------

proj = QgsProject.instance()
_tr = QgsCoordinateTransform(
    QgsCoordinateReferenceSystem("EPSG:2154"),
    QgsCoordinateReferenceSystem("EPSG:4326"),
    proj,
)


# --- Restauration des accents ------------------------------------------
# Les textes saisis dans la couche QGIS sont sans accents (champs `regime`,
# `diagnostic`, `zoneRefuge`...). On les restaure à l'export pour que la
# webmap affiche un français correct ; la couche source n'est pas modifiée.
# Liste volontairement limitée aux mots présents dans ces textes : tout
# nouveau mot sans accent doit être ajouté ici.
# Phrases d'abord (contexte), puis mots.
PHRASES = [
    ("etre cale", "être calé"),
    ("lies a l'existant", "liés à l'existant"),
    ("l'etat", "l'état"),
    ("a cet endroit", "à cet endroit"),
    ("par rapport a la", "par rapport à la"),
    ("fonctionnelle a justifier", "fonctionnelle à justifier"),
    ("alea faible a moyen", "aléa faible à moyen"),
    ("limitee a ", "limitée à "),
    ("FPRNM a ", "FPRNM à "),
    ("mises en oeuvre", "mises en œuvre"),
    ("mise en oeuvre", "mise en œuvre"),
    ("<=", "≤"),
]
WORDS = {
    "autorisees":"autorisées","autorisee":"autorisée","ecoulement":"écoulement","materiaux":"matériaux",
    "vulnerables":"vulnérables","etablissements":"établissements","hebergement":"hébergement",
    "activites":"activités","activite":"activité","memes":"mêmes","meme":"même","regime":"régime",
    "tres":"très","acces":"accès","securite":"sécurité","legers":"légers","demontables":"démontables",
    "batiments":"bâtiments","limitees":"limitées","limitee":"limitée","impossibilite":"impossibilité",
    "etude":"étude","geotechnique":"géotechnique","necessitant":"nécessitant","reseaux":"réseaux",
    "etanches":"étanches","surexhausse":"surexhaussé","capacite":"capacité","dument":"dûment",
    "justifiee":"justifiée","adapte":"adapté","exige":"exigé","vulnerabilite":"vulnérabilité",
    "alea":"aléa","delai":"délai","chiffre":"chiffré","venale":"vénale","eligible":"éligible",
    "determine":"déterminé","qualifiee":"qualifiée","reserve":"réserve","salaries":"salariés",
    "lineaire":"linéaire","reference":"référence","surealeve":"surélevé","interpolee":"interpolée",
    "estime":"estimé","fiabilite":"fiabilité","moderee":"modérée","etage":"étage","donnee":"donnée",
    "millesime":"millésime","economique":"économique","indeterminee":"indéterminée","habitee":"habitée",
}

def restore(s):
    if not isinstance(s, str):
        return s
    for a, b in PHRASES:
        s = s.replace(a, b)
    def sub(m):
        w = m.group(0)
        r = WORDS.get(w.lower())
        if r is None:
            return w
        return r[0].upper() + r[1:] if w[0].isupper() else r
    s = re.sub(r"[A-Za-z]+", sub, s)
    s = re.sub(r"(\d) m2\b", r"\1 m²", s)
    return s

TEXT_FIELDS = (
    "zoneLabel", "regime", "diagnostic", "zoneRefuge", "refugeCategorie",
    "eligibiliteFprnm", "hauteurEauNote", "coteReferenceMethode",
    "etageSource", "typologie", "typologieSource",
)


def clean(v):
    return None if (v is None or v == NULL) else v


def geom_to_geojson(geom, ndigits=6, simplify_tol=None):
    g = QgsGeometry(geom)
    if simplify_tol:
        g = g.simplify(simplify_tol)
    g.transform(_tr)
    gj = json.loads(g.asJson())

    def round_coords(c):
        if isinstance(c[0], list):
            return [round_coords(x) for x in c]
        return [round(c[0], ndigits), round(c[1], ndigits)]

    gj["coordinates"] = round_coords(gj["coordinates"])
    return gj


def find_layer(name):
    matches = [l for l in proj.mapLayers().values() if l.name() == name]
    if not matches:
        raise RuntimeError(f"Couche introuvable : {name}")
    return matches[0]


def write_geojson(path, features):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"type": "FeatureCollection", "features": features},
            fh,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    print(f"  -> {path} ({len(features)} entités, {os.path.getsize(path)/1e6:.2f} Mo)")


def export_bati():
    lyr = find_layer(LAYER_BATI)
    feats_zone, feats_hors = [], []
    for f in lyr.getFeatures():
        zone_code = clean(f["zoneCode"])
        if zone_code is None:
            geom = geom_to_geojson(f.geometry(), ndigits=5, simplify_tol=0.5)
            feats_hors.append(
                {"type": "Feature", "geometry": geom, "properties": {"id": clean(f["id"])}}
            )
            continue
        geom = geom_to_geojson(f.geometry(), ndigits=6, simplify_tol=0.15)
        h_eau = clean(f["hauteurEauEstimeeM"])
        if h_eau is not None and h_eau < 0:
            h_eau = 0.0  # par défaut, une hauteur négative n'est pas affichée (ramenée à 0)
        props = {
            "id": clean(f["id"]),
            "zoneCode": zone_code,
            "zoneLabel": clean(f["zoneLabel"]) or ZONE_LABELS.get(zone_code, zone_code),
            "zoneColor": clean(f["zoneColor"]) or ZONE_COLORS.get(zone_code, "#9E9E9E"),
            "concerne": True,
            "regime": clean(f["regime"]),
            "diagnostic": clean(f["diagnostic"]),
            "zoneRefuge": clean(f["zoneRefuge"]),
            "refugeCategorie": clean(f["refugeCategorie"]),
            "etagePresent": clean(f["etagePresent"]),
            "etageSource": clean(f["etageSource"]),
            "typologie": clean(f["typologie"]),
            "typologieSource": clean(f["typologieSource"]),
            "eligibiliteFprnm": clean(f["eligibiliteFprnm"]),
            "etudeGeotechniqueG2": clean(f["etudeGeotechniqueG2"]),
            "hauteurM": clean(f["hauteurM"]),
            "altitudeSolLidarHdM": clean(f["altitudeSolLidarHdM"]),
            "coteReferencePheM": clean(f["coteReferencePheM"]),
            "coteReferenceMethode": clean(f["coteReferenceMethode"]),
            "distanceIsocoteM": clean(f["distanceIsocoteM"]),
            "hauteurEauEstimeeM": h_eau,
            "hauteurEauNote": clean(f["hauteurEauNote"]),
        }
        props = {k: v for k, v in props.items() if v is not None}
        for k in TEXT_FIELDS:
            if k in props:
                props[k] = restore(props[k])
        feats_zone.append({"type": "Feature", "geometry": geom, "properties": props})

    write_geojson(os.path.join(OUTPUT_DIR, "batiments_ppri.geojson"), feats_zone)
    write_geojson(os.path.join(OUTPUT_DIR, "batiments_hors_zone.geojson"), feats_hors)


def export_zonage():
    lyr = find_layer(LAYER_ZONAGE)
    feats = []
    for f in lyr.getFeatures():
        code = clean(f["zoneCode"])
        props = {
            "zoneCode": code,
            "zoneLabel": clean(f["zoneLabel"]) or ZONE_LABELS.get(code, code),
            "zoneColor": clean(f["zoneColor"]) or ZONE_COLORS.get(code, "#9E9E9E"),
            "codeZone": clean(f["codeZone"]),
            "typeReg": clean(f["typeReg"]),
            "libelleZone": clean(f["libelleZone"]),
        }
        props = {k: v for k, v in props.items() if v is not None}
        geom = geom_to_geojson(f.geometry(), ndigits=6, simplify_tol=0.2)
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    write_geojson(os.path.join(OUTPUT_DIR, "zonage_pprin.geojson"), feats)


def export_hauteur_eau():
    """Couche de hauteur d'eau estimée (polygones classés), voir
    docs/METHODOLOGIE.md §8. Filtrée (parties < 50 m² écartées) et
    simplifiée (tolérance 5 m) en amont dans le projet QGIS pour limiter
    le poids du fichier publié."""
    lyr = find_layer(LAYER_HAUTEUR_EAU)
    feats = []
    for f in lyr.getFeatures():
        props = {
            "classe": clean(f["classe"]),
            "classeLabel": clean(f["classeLabel"]),
            "classeColor": clean(f["classeColor"]),
        }
        props = {k: v for k, v in props.items() if v is not None}
        geom = geom_to_geojson(f.geometry(), ndigits=6)
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    write_geojson(os.path.join(OUTPUT_DIR, "hauteur_eau.geojson"), feats)


def export_erp():
    """Pas de couche ERP disponible pour Quint-Fonsegrives à ce jour (voir
    faq.html) : fichier vide, pour que src/js/app.js puisse le charger sans
    erreur. À remplacer par une vraie lecture de couche (voir l'ancienne
    implémentation dans l'historique git) dès qu'une source ERP existe."""
    write_geojson(os.path.join(OUTPUT_DIR, "erp.geojson"), [])


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("Export des couches vers data/ ...")
    export_bati()
    export_zonage()
    export_hauteur_eau()
    export_erp()
    print("Terminé.")
