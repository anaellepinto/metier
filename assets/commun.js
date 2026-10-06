/* ============================================================
   commun.js — ce que les cinq pages partagent.
   Chargé par index.html, salaires.html, exigences.html,
   recruteurs.html et mouvement.html, après Chart.js.

   Tout est déclaré au premier niveau : le petit script de chaque
   page peut donc appeler directement euro(), barres(), NIVEAUX…
   Une page ne fait plus que deux choses : son HTML de section, et
   Commun.demarrer(rendre) où rendre(offres, D) dessine SES
   graphiques à chaque changement de filtre.
   ============================================================ */

/* ============================================================
   1) UTILITAIRES
   ============================================================ */
const euro = (n, pas = 1) => n == null || !isFinite(n) ? "—" : (Math.round(n / pas) * pas).toLocaleString("fr-FR") + " €";
const net = brutAnnuel => brutAnnuel * 0.78 / 12;
const pct = (a, b) => b ? Math.round(100 * a / b) : 0;
const mediane = a => quantile(a, .5);
function quantile(a, q) {
  const s = a.filter(x => x != null && isFinite(x)).sort((x, y) => x - y);
  if (!s.length) return null;
  const p = (s.length - 1) * q, bas = Math.floor(p), haut = Math.ceil(p);
  return bas === haut ? s[bas] : s[bas] + (s[haut] - s[bas]) * (p - bas);
}
const compter = (liste, cle) => { const c = new Map(); for (const x of liste) { const k = cle(x); if (k == null || k === "") continue; c.set(k, (c.get(k) || 0) + 1); } return [...c].sort((a, b) => b[1] - a[1]); };
const court = (s, n) => !s ? "—" : (s.length > n ? s.slice(0, n - 1) + "…" : s);
/* Le libellé de salaire de France Travail, rendu lisible : « Mensuel de 2500.0 Euros à
   2500.0 Euros » -> « 2 500 € brut par mois ». Le commentaire libre qui suit un tiret
   (« - Salaire horaire : Smic horaire (+ majoration…) ») est coupé : il fait trois lignes
   dans une liste compacte et n'ajoute rien au chiffre. */
function salaireCourt(o) {
  const lib = String(o.salaire || "").split(" - ")[0].trim();
  if (!lib) return "";
  const m = /^(annuel|mensuel|horaire)\s+de\s+([\d.,]+)\s*euros(?:\s*à\s*([\d.,]+)\s*euros)?/i.exec(lib);
  if (!m) return court(lib, 60);
  const periode = { annuel: "par an", mensuel: "par mois", horaire: "de l'heure" }[m[1].toLowerCase()];
  const nb = v => Number(String(v).replace(",", "."));
  const somme = v => nb(v).toLocaleString("fr-FR", { maximumFractionDigits: 2 }) + " €";
  const haut = m[3] && nb(m[3]) > nb(m[2]) ? somme(m[3]) : null;
  return (haut ? somme(m[2]) + " à " + haut : somme(m[2])) + " brut " + periode;
}
/* Coupe un libellé long en lignes courtes : Chart.js affiche un tableau sur
   plusieurs lignes, donc rien n'est tronqué, même sur un écran de 400 px. */
function enLignes(texte, max = 28) {
  const lignes = [];
  let ligne = "";
  for (const mot of String(texte).split(" ")) {
    if (ligne && (ligne + " " + mot).length > max) { lignes.push(ligne); ligne = mot; }
    else ligne = ligne ? ligne + " " + mot : mot;
  }
  if (ligne) lignes.push(ligne);
  return lignes;
}
const ans = v => v == null ? "—" : v === 0 ? "débutant" : v < 1 ? Math.round(v * 12) + " mois" : (Math.round(v * 10) / 10).toLocaleString("fr-FR") + (v >= 2 ? " ans" : " an");
// 2026-09-22 -> 22/09/2026 (ou 22/09 pour les étiquettes de graphique).
const dateFr = (s, bref = false) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ""); return m ? (bref ? `${m[3]}/${m[2]}` : `${m[3]}/${m[2]}/${m[1]}`) : (s || "?"); };
// Âge d'une annonce en jours, par rapport à la date d'extraction.
const age = o => { const jour = Date.parse(D.date), t = Date.parse(o.date); return (isFinite(jour) && isFinite(t)) ? (jour - t) / 86400000 : null; };

const couleur = "#e0197d", pale = "rgba(224,25,125,.25)";
const COULEURS = { Marketing: "#e0197d", Digital: "#ff6a00", Frontière: "#8e8e93" };
// Les groupes des autres onglets prennent ces teintes, dans l'ordre où leur onglet les liste.
const TEINTES_GROUPES = ["#e0197d", "#ff6a00", "#1a9e77", "#7b3fe4", "#8e8e93"];
// Palette des niveaux : du clair au foncé, assistant → directeur, « autre » en gris. Valable sur toute la page.
const COUL_NIV = { assistant: "#f9b8d8", charge: "#ee6aab", responsable: "#c2185b", directeur: "#7a0f45", autre: "#b4b4bc" };
// Sur ces trois teintes claires, le texte blanc n'est pas lisible : on écrit en encre foncée.
const ENCRE_FONCEE = new Set(["assistant", "charge", "autre"]);
const NIVEAUX_DEFAUT = [["assistant", "Assistant·e / junior"], ["charge", "Chargé·e"], ["responsable", "Responsable"], ["directeur", "Directeur·rice"], ["autre", "Autre"]];
const FORMATIONS_DEFAUT = ["< Bac", "Bac", "Bac+2", "Bac+3/4", "Bac+5"];
// Sept familles de contrat, exclusives : une offre tombe dans une seule.
const CONTRATS = [["cdi", "CDI"], ["cdd", "CDD"], ["stage", "Stage"], ["alt", "Alternance"], ["mis", "Intérim"], ["indep", "Indépendant"], ["autre", "Autre"]];
const AURA = new Set(["01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"]);
const IDF = new Set(["75", "77", "78", "91", "92", "93", "94", "95"]);
const EXPS = ["Débutant accepté", "Moins d'un an", "1 à 2 ans", "3 à 4 ans", "5 ans et plus", "Non précisé"];

/* Noms des départements (référentiel officiel), pour écrire « Paris (75) » plutôt que « 75 ». */
const DEPARTEMENTS = { "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence", "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes", "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron", "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente", "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud", "2B": "Haute-Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure", "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers", "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre", "37": "Indre-et-Loire", "38": "Isère", "39": "Jura", "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire", "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche", "51": "Marne", "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord", "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie", "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres", "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse", "85": "Vendée", "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort", "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise", "971": "Guadeloupe", "972": "Martinique", "973": "Guyane", "974": "La Réunion", "975": "Saint-Pierre-et-Miquelon", "976": "Mayotte", "977": "Saint-Barthélemy", "978": "Saint-Martin" };
/* Le département d'une offre. Outre-mer : resume.json ne garde que « 97 », le lieu de l'annonce
   (« 974 - Saint-Louis ») donne le code complet. */
function depDe(o) {
  if (o.dep !== "97") return o.dep || null;
  const m = /^\s*(97\d)/.exec(o.lieu || "");
  return m ? m[1] : "97";
}
const libDep = code => DEPARTEMENTS[code] ? `${DEPARTEMENTS[code]} (${code})` : (code === "97" ? "Outre-mer (97)" : code);

/* Milliers d'euros, une décimale au plus : 22 800 -> « 22,8 », 40 000 -> « 40 ». */
const kilo = v => (Math.round(v / 100) / 10).toLocaleString("fr-FR");
const plage = (a, b) => Math.round(a / 100) === Math.round(b / 100) ? `${kilo(a)} k€` : `${kilo(a)} – ${kilo(b)} k€`;
const nombre = v => Number(v).toLocaleString("fr-FR");
const pluriel = (k, mot = "offre") => `${nombre(k)} ${mot}${k > 1 ? "s" : ""}`;
const ETROIT = () => window.innerWidth < 560;

/* « MANPOWER FRANCE » -> « Manpower France » : les noms tout en capitales sont remis en casse
   de titre ; les sigles courts (EFC, ISCOD, BIO3G) et les noms déjà en minuscules sont laissés. */
function joliNom(nom) {
  if (!nom) return nom;
  const PETITS = new Set(["DE", "DU", "DES", "LA", "LE", "LES", "ET", "EN", "AU", "AUX", "D", "L"]);
  return nom.split(" ").map((m, i) => {
    if (m !== m.toUpperCase() || /\d|\./.test(m)) return m;
    if (i > 0 && PETITS.has(m)) return m.toLowerCase();
    return m.length <= 5 ? m : m[0] + m.slice(1).toLowerCase();
  }).join(" ");
}

/* Profil d'un annonceur, lu dans ses propres annonces (contrat et secteur déclarés) : la donnée
   ne dit pas « école » ou « plateforme », elle dit seulement ce que l'annonceur publie. */
const INTERIM = /travail temporaire|placement de main-d'?(œ|oe)uvre|mise à disposition de ressources humaines/i;
function profilAnnonceur(lot) {
  const part = test => lot.filter(test).length / (lot.length || 1);
  if (part(o => familleContrat(o) === "indep") > .5) return "indep";
  if (part(o => familleContrat(o) === "mis" || INTERIM.test(o.secteur || "")) > .5) return "interim";
  if (part(o => familleContrat(o) === "alt") > .5) return "alt";
  return "direct";
}
const GRIS = "#b4b4bc", ROSE_PALE = "#f4a3cb";
const estIntermediaire = profil => profil === "indep" || profil === "interim";

/* Annonces identiques (même employeur, même intitulé) comptées une seule fois : un réseau qui
   publie 190 fois le même texte ne doit pas peser 190 fois dans une part d'annonces. */
function sansRepetitions(offres) {
  const vues = new Set();
  return offres.filter(o => {
    if (!o.entreprise) return true;
    const k = o.entreprise.toLowerCase() + "|" + String(o.intitule || "").toLowerCase().replace(/\(?\b[hf]\s*\/\s*[hf]\b\)?/g, "").replace(/[^a-zà-ÿ0-9]+/g, " ").trim();
    if (vues.has(k)) return false;
    vues.add(k); return true;
  });
}

/* La ligne de source sous chaque graphique : une capture d'écran reste sourcée. */
const NOM_SOURCE = { "France Travail": "France Travail (API Offres d'emploi v2)" };
function source(id, lot, precision = "") {
  const e = document.getElementById(id);
  if (!e) return;
  const noms = [...new Set(lot.map(sourceDe))].sort((a, b) => (a === SOURCE_DEFAUT ? -1 : b === SOURCE_DEFAUT ? 1 : a.localeCompare(b)));
  e.textContent = `Source : ${noms.map(s => NOM_SOURCE[s] || s).join(" ; ") || NOM_SOURCE[SOURCE_DEFAUT]} · extraction du ${dateFr(D.date)} · n = ${pluriel(lot.length)}${precision ? " · " + precision : ""}`;
}

Chart.defaults.font.family = "system-ui, -apple-system, 'Segoe UI', sans-serif";
Chart.defaults.plugins.legend.display = false;
// Valeurs écrites sur les graphiques (chartjs-plugin-datalabels) : éteintes par défaut, chaque graphique les allume.
if (window.ChartDataLabels) { Chart.register(ChartDataLabels); Chart.defaults.plugins.datalabels = Object.assign(Chart.defaults.plugins.datalabels || {}, { display: false }); }
const ENCRE = "#1d1d1f", ENCRE_GRISE = "#6e6e73";
/* Ligne verticale de repère (ex. la médiane d'ensemble) : options.plugins.repere = { valeur, texte }. */
Chart.register({ id: "repere", afterDatasetsDraw(c, _a, opt) {
  if (!opt || opt.valeur == null || !c.scales.x) return;
  const x = c.scales.x.getPixelForValue(opt.valeur), { top, bottom } = c.chartArea, g = c.ctx;
  g.save(); g.strokeStyle = ENCRE_GRISE; g.setLineDash([4, 4]); g.lineWidth = 1;
  g.beginPath(); g.moveTo(x, top); g.lineTo(x, bottom); g.stroke();
  if (opt.texte) { g.setLineDash([]); g.fillStyle = ENCRE_GRISE; g.font = "11px " + Chart.defaults.font.family; g.textAlign = "center"; g.fillText(opt.texte, x, top - 6); }
  g.restore();
} });

let D, graphiques = {};
let NIVEAUX = NIVEAUX_DEFAUT, FORMATIONS = FORMATIONS_DEFAUT;

/* Famille de contrat d'une offre. Le stage d'abord : France Travail n'a pas de contrat « stage »
   et le range sous un CDI ou un CDD, c'est l'intitulé qui le dit (resumer.py, est_stage).
   Puis l'alternance, qui l'emporte sur le CDI/CDD qui la porte. */
function familleContrat(o) {
  const c = o.contrat || "", nat = o.nature || "";
  if (o.stage) return "stage";
  if (o.alternance || nat === "apprentissage" || nat === "professionnalisation") return "alt";
  if (c === "MIS") return "mis";
  if (c === "LIB" || c === "FRA" || c === "CCE" || nat === "non_salarie") return "indep";
  if (c === "CDI") return "cdi";
  if (c === "CDD") return "cdd";
  return "autre";
}
const niv = o => (o && COUL_NIV[o.niveau]) ? o.niveau : "autre";
const libNiv = k => (NIVEAUX.find(x => x[0] === k) || [k, k])[1];
const libContrat = code => (D && D.contrats && D.contrats[code]) || code || "Non précisé";
/* Le contrat tel qu'on l'annonce au lecteur : le stage et l'alternance passent devant le
   CDI/CDD qui les porte, pour dire partout la même chose que le filtre. */
const libContratOffre = o => ({ stage: "Stage", alt: "Alternance" })[familleContrat(o)] || libContrat(o.contrat);
/* La source d'une offre, et le site partenaire d'où France Travail l'a reprise. */
const SOURCE_DEFAUT = "France Travail";
const sourceDe = o => o.source || SOURCE_DEFAUT;
const libSource = o => sourceDe(o) + (o.partenaire ? " · via " + o.partenaire : "");
// Une couleur par source, reprise par l'étiquette des offres et par la case du filtre.
const COUL_SOURCES = { "France Travail": "#1a5fb4", "La bonne alternance": "#1a9e77", "Adzuna": "#7b3fe4", "Jooble": "#c25e00" };
const couleurSource = s => COUL_SOURCES[s] || "#6e6e73";
const etiqSource = o => `<span class="etiq source" style="color:${couleurSource(sourceDe(o))}" title="Source de l'annonce">${libSource(o)}</span>`;

/* Une offre ouverte aux débutants. L'accueil annonce ce chiffre dans son lien vers
   « Ce qu'on vous demande », qui l'affiche aussi : une seule règle écrite une fois,
   pour que les deux pages ne puissent pas se contredire. */
const debutantAccepte = o => o.exp_exige === "D" || o.exp_ans === 0;

/* Tranche d'expérience demandée. */
function trancheExp(o) {
  if (o.exp_exige === "D" || o.exp_ans === 0) return "Débutant accepté";
  if (o.exp_ans == null) return "Non précisé";
  if (o.exp_ans < 1) return "Moins d'un an";
  if (o.exp_ans < 3) return "1 à 2 ans";
  if (o.exp_ans < 5) return "3 à 4 ans";
  return "5 ans et plus";
}

/* Secteurs : libellés officiels très longs, on les rend lisibles. */
const RACCOURCIS = [
  [/agences de travail temporaire/i, "Agences d'intérim"],
  [/placement de main-d'?œuvre|placement de main-d'?oeuvre/i, "Placement de main-d'œuvre"],
  [/mise à disposition de ressources humaines/i, "Mise à disposition de personnel"],
  [/relations publiques et communication/i, "Conseil en communication"],
  [/conseil pour les affaires et autres conseils de gestion/i, "Conseil en gestion"],
  [/programmation informatique/i, "Programmation informatique"],
  [/portails internet/i, "Portails internet"],
  [/régie publicitaire/i, "Régie publicitaire"],
  [/agences de publicité/i, "Agences de publicité"],
  [/commerce de détail/i, "Commerce de détail"],
];
function secteurCourt(s) {
  if (!s) return null;
  for (const [re, lib] of RACCOURCIS) if (re.test(s)) return lib;
  return court(s.replace(/^Activités? (de(s)? |d'|du )?/i, "").replace(/^./, c => c.toUpperCase()), 48);
}

/* ============================================================
   2) GRAPHIQUES : création la première fois, mise à jour ensuite
   ============================================================ */
function dessiner(id, type, data, options) {
  const el = document.getElementById(id);
  if (!el) return null;
  // resize() avant update() : la hauteur de la zone peut avoir changé avec le nombre de barres.
  const opts = Object.assign({ responsive: true, maintainAspectRatio: false, animation: false }, options);
  // Les options aussi sont reposées : une échelle ou un repère dépendent des filtres.
  if (graphiques[id]) { const g = graphiques[id]; g.data.labels = data.labels; g.data.datasets = data.datasets; g.options = opts; g.resize(); g.update(); return g; }
  graphiques[id] = new Chart(el, { type, data, options: opts });
  return graphiques[id];
}

/* Un graphique en barres horizontales doit grandir avec le nombre de barres :
   sinon Chart.js masque une étiquette sur deux et on ne sait plus qui est qui. */
function zoneSelonBarres(id, n, parBarre = 28, marge = 16) {
  const el = document.getElementById(id);
  if (el) el.parentNode.style.height = Math.max(70, marge + n * parBarre) + "px";
}

/* Barres horizontales simples, une seule série. La valeur est écrite au bout de la barre :
   plus besoin d'axe ni de grille. opt : { teinte (une couleur ou une par barre), texte(v, i)
   pour l'étiquette, parBarre (hauteur d'une ligne) }. */
function barres(id, etiquettes, valeurs, opt = {}) {
  const texte = opt.texte || (v => nombre(v));
  const lignesMax = Math.max(1, ...etiquettes.map(e => Array.isArray(e) ? e.length : 1));
  zoneSelonBarres(id, etiquettes.length, opt.parBarre || (lignesMax > 1 ? 14 + 14 * lignesMax : 28));
  dessiner(id, "bar",
    { labels: etiquettes, datasets: [{ data: valeurs, backgroundColor: opt.teinte || couleur, borderRadius: 3, barPercentage: .78, categoryPercentage: .9 }] },
    { indexAxis: "y",
      layout: { padding: { right: opt.marge || 76 } },
      plugins: { tooltip: { callbacks: { label: c => texte(c.parsed.x, c.dataIndex) } },
                 datalabels: { display: true, anchor: "end", align: "right", offset: 4, color: ENCRE, font: { size: 12, weight: 600 }, formatter: (v, c) => texte(v, c.dataIndex) } },
      scales: { x: { display: false, beginAtZero: true },
                y: { grid: { display: false }, border: { display: false }, ticks: { autoSkip: false, color: ENCRE, font: { size: 12 } } } } });
}

/* Barres flottantes : de la médiane des minima à la médiane des maxima. */
function fourchette(lot) {
  const mn = mediane(lot.map(o => o.smin).filter(v => v != null));
  if (mn == null) return null;
  const mx = mediane(lot.map(o => (o.smax != null ? o.smax : o.smin)).filter(v => v != null));
  return [mn, Math.max(mx == null ? mn : mx, mn)];
}
/* Bornes d'axe communes à plusieurs graphiques de fourchettes : un axe qui part de zéro
   laisse un tiers de la largeur vide, une barre flottante n'en a pas besoin. */
function bornes(paires, pas = 5000) {
  const v = paires.filter(Boolean).flat();
  if (!v.length) return {};
  return { min: Math.max(0, Math.floor((Math.min(...v) - pas * .6) / pas) * pas), max: Math.ceil((Math.max(...v) + pas * .2) / pas) * pas };
}
/* lignes : [{ label, n, paire:[min,max], teinte, bord, faible }] ; opt : { min, max, repere:{valeur,texte}, unite(a,b), parBarre } */
function flottantes(id, lignes, opt = {}) {
  const ecrit = opt.unite || plage, b = opt.min != null ? opt : bornes(lignes.map(l => l.paire)), etroit = ETROIT();
  zoneSelonBarres(id, lignes.length, opt.parBarre || (etroit ? 56 : 44), opt.repere ? 62 : 44);
  dessiner(id, "bar",
    // Sur un écran étroit, « effectif faible » passe à la ligne : sinon l'étiquette est rognée à gauche.
    { labels: lignes.map(l => [].concat(l.label, etroit && l.faible ? [pluriel(l.n), "effectif faible"] : pluriel(l.n) + (l.faible ? " · effectif faible" : ""))),
      datasets: [{ data: lignes.map(l => l.paire), backgroundColor: lignes.map(l => l.teinte || couleur),
        borderColor: lignes.map(l => l.bord || "transparent"), borderWidth: lignes.map(l => l.bord ? 1.5 : 0),
        borderRadius: 4, borderSkipped: false, minBarLength: 7, barPercentage: .62 }] },
    { indexAxis: "y",
      layout: { padding: { right: etroit ? 92 : 104, top: opt.repere ? 18 : 0 } },
      plugins: { repere: opt.repere || {},
        tooltip: { callbacks: { label: c => { const r = c.raw || []; return r.length < 2 ? "" : (opt.infobulle ? opt.infobulle(r) :
          [`${euro(r[0], 100)} → ${euro(r[1], 100)} brut par an`, `soit ${euro(net(r[0]), 10)} → ${euro(net(r[1]), 10)} net par mois`]); } } },
        datalabels: { display: true, anchor: "end", align: "right", offset: 6, color: ENCRE, font: { size: 12, weight: 600 }, formatter: v => Array.isArray(v) ? ecrit(v[0], v[1]) : "" } },
      scales: { x: { min: b.min, max: b.max, grid: { display: false }, border: { color: "#d2d2d7" }, ticks: { color: ENCRE_GRISE, maxTicksLimit: 7, callback: opt.graduation || (v => Math.round(v / 1000) + " k€") } },
                y: { grid: { display: false }, border: { display: false }, ticks: { autoSkip: false, color: ENCRE, font: { size: etroit ? 11 : 12 } } } } });
}

/* ============================================================
   3) ÉTAT DES FILTRES
   ============================================================ */
/* Couleur d'un groupe de l'onglet affiché, et d'un métier selon son groupe dans cet onglet. */
function couleurGroupe(g) {
  if (COULEURS[g]) return COULEURS[g];
  const i = Commun.onglet ? Commun.onglet.groupes.findIndex(x => x.nom === g) : -1;
  return i >= 0 ? TEINTES_GROUPES[i % TEINTES_GROUPES.length] : couleur;
}
const couleurMetier = code => couleurGroupe(Commun.groupeDe[code]);

const cochees = sel => new Set([...document.querySelectorAll(sel + " input:checked")].map(i => i.value));
function etatFiltres() {
  // Le filtre des sources n'est affiché que s'il y en a plusieurs : masqué, il laisse tout passer.
  const bloc = document.getElementById("bloc-sources");
  const sources = bloc && !bloc.hidden ? cochees("#f-sources") : null;
  return { metiers: cochees("#metiers"), contrats: cochees("#f-contrats"), niveaux: cochees("#f-niveaux"), sources };
}
/* Les offres retenues par les filtres. */
function filtrer(f) {
  f = f || etatFiltres();
  return D.offres.filter(o => f.metiers.has(o.rome) && f.contrats.has(familleContrat(o)) && f.niveaux.has(niv(o))
    && (!f.sources || f.sources.has(sourceDe(o))));
}

/* ============================================================
   4) NAVIGATION ET PANNEAU DE FILTRES, IDENTIQUES PARTOUT
   ============================================================ */
const PAGES = [
  ["index.html", "Accueil"],
  ["salaires.html", "Rémunération"],
  ["exigences.html", "Missions"],
  ["recruteurs.html", "Qui recrute ?"],
  ["mouvement.html", "Les évolutions"],
];
// Chemins relatifs partout : le site vit dans un sous-dossier (/metier/) sur GitHub Pages.
const PAGE_ICI = (location.pathname.split("/").pop() || "index.html");

const HTML_FILTRES = `
  <div class="filtres">
    <div>
      <h3>Les métiers</h3>
      <div class="metiers" id="metiers"></div>
      <div class="boutons">
        <button data-groupe="tous">Tout cocher</button>
        <button data-groupe="aucun">Tout décocher</button>
        <span class="groupes" id="groupes"></span>
      </div>
    </div>
    <div>
      <h3>Type de contrat</h3>
      <div class="cases" id="f-contrats"></div>
    </div>
    <div>
      <h3>Niveau de poste</h3>
      <div class="cases" id="f-niveaux"></div>
      <p class="note" style="margin:8px 0 0">Déduit de l'intitulé de l'annonce. Ces couleurs servent de repère dans toute la page.</p>
    </div>
    <div id="bloc-sources" hidden>
      <h3>Source</h3>
      <div class="cases" id="f-sources"></div>
    </div>
  </div>
  <p class="compte" id="compte"></p>`;

function poserNavEtFiltres() {
  const n = document.getElementById("nav-ici");
  if (n) n.outerHTML = `<nav class="nav">` + PAGES.map(([url, lib]) =>
    `<a href="${url}"${url === PAGE_ICI ? ' class="ici" aria-current="page"' : ""}>${lib}</a>`).join("") + `</nav>`;

  const f = document.getElementById("filtres-ici");
  // Les onglets restent visibles au-dessus du panneau, même replié : ils disent quels métiers on lit.
  if (f) f.outerHTML = `<div class="onglets" id="onglets" role="tablist" aria-label="Familles de métiers" hidden></div>`
    + (PAGE_ICI === "index.html"
    // Accueil : le panneau est déplié, c'est le point de départ.
    ? `<div class="carte">${HTML_FILTRES}</div>`
    // Ailleurs : replié, on vient lire une page, pas refaire ses filtres.
    : `<details class="carte"><summary id="resume-filtres">Filtres</summary>${HTML_FILTRES}</details>`)
    + `<div class="vide" id="aucune" hidden>Aucune offre ne correspond à ces filtres. Recochez un métier, un type de contrat, un niveau de poste ou une source.</div>`;

  const p = document.getElementById("pied");
  if (p) p.innerHTML =
    `<p style="margin:0 0 8px"><a href="mouvement.html#limites">Limites de ces chiffres</a></p>
     Sources : API France Travail (<code>scripts/extraire.py</code>) ; La bonne alternance, Adzuna et Jooble, par leurs API officielles (<code>scripts/autres_sources.py</code>), quand leurs clés sont configurées.<br>
     Chaîne : API France Travail → <code>scripts/extraire.py</code> → <code>data/brut/</code> (chaque version d'annonce, une seule fois) + <code>data/actives/</code> (les offres du jour) → <code>scripts/resumer.py</code> → <code>data/resume.json</code> → ces pages (GitHub Pages).
     Une Action GitHub relance la collecte chaque matin, pour un site à jour à 7 h ; une offre absente de la collecte du jour (expirée, pourvue ou retirée) disparaît du site. Identifiants dans les secrets du dépôt, jamais dans le code.
     Dépôt de démonstration — M2 MOD, IAE Clermont Auvergne, séminaires métiers.`;
}

/* ============================================================
   5) ONGLETS : une famille de métiers par onglet
   Chaque onglet a ses groupes, ses métiers et ses propres filtres
   mémorisés ; changer d'onglet reconstruit le panneau et redessine
   la page, sans la recharger.
   ============================================================ */

/* Les onglets du resume.json ; un ancien fichier sans onglets en donne un seul, bâti sur les groupes. */
function ongletsDe(d) {
  if (Array.isArray(d.onglets) && d.onglets.length) return d.onglets;
  const groupes = [...new Set(d.metiers.map(m => m.groupe))];
  return [{ id: "tous", titre: "Tous les métiers", groupes: groupes.map(g => {
    const ms = d.metiers.filter(m => m.groupe === g);
    return { nom: g, codes: ms.map(m => m.code), coche: ms.some(m => m.coche) };
  }) }];
}

/* Filtres mémorisés : { onglet, par_onglet: { id: { metiers, contrats, niveaux } } }.
   L'ancien format (un seul jeu de filtres) est repris pour le premier onglet. */
function lireMemo(onglets) {
  let m = null;
  try { m = JSON.parse(localStorage.getItem("metiers-filtres")); } catch (e) {}
  if (!m) { try { const vieux = JSON.parse(localStorage.getItem("metiers-coches")); if (Array.isArray(vieux)) m = { metiers: vieux }; } catch (e) {} }
  if (m && m.par_onglet) return m;
  return { onglet: onglets[0].id, par_onglet: m ? { [onglets[0].id]: m } : {} };
}

/* Cases de groupe : cochée si tout le groupe l'est, état intermédiaire s'il l'est en partie. */
function majGroupes() {
  document.querySelectorAll("[data-groupe-case]").forEach(c => {
    const cases = [...document.querySelectorAll(`#metiers input[data-groupe="${c.dataset.groupeCase}"]`)];
    const k = cases.filter(i => i.checked).length;
    c.checked = cases.length > 0 && k === cases.length; c.indeterminate = k > 0 && k < cases.length;
  });
}

/* Affiche un onglet : bouton actif, métiers de ses groupes, et ses filtres mémorisés. */
function poserOnglet(id) {
  const o = Commun.onglets.find(x => x.id === id) || Commun.onglets[0];
  Commun.onglet = o;
  Commun.groupeDe = {};
  o.groupes.forEach(g => g.codes.forEach(c => { Commun.groupeDe[c] = g.nom; }));
  Commun.memo.onglet = o.id;
  document.querySelectorAll("#onglets [role=tab]").forEach(b => {
    const ici = b.dataset.onglet === o.id;
    b.setAttribute("aria-selected", ici); b.tabIndex = ici ? 0 : -1;
  });

  const memo = Commun.memo.par_onglet[o.id] || {};
  const memoA = (cle, defaut) => Array.isArray(memo[cle]) ? memo[cle] : defaut;
  const memoM = memoA("metiers", null);
  document.getElementById("metiers").innerHTML = o.groupes.map(g => `<h4 style="color:${couleurGroupe(g.nom)}">${g.nom}</h4>` +
    g.codes.map(c => { const m = Commun.lib[c] || { libelle: c, actives: 0 };
      return `<label><input type="checkbox" value="${c}" data-groupe="${g.nom}" ${(memoM ? memoM.includes(c) : g.coche) ? "checked" : ""}> ${m.libelle} <small>${c} · ${m.actives}</small></label>`; }).join("")).join("");
  document.getElementById("groupes").innerHTML = o.groupes.map(g =>
    `<label style="color:${couleurGroupe(g.nom)}"><input type="checkbox" data-groupe-case="${g.nom}"> ${g.nom}</label>`).join("");
  majGroupes();

  const memoC = memoA("contrats", CONTRATS.map(x => x[0])), memoN = memoA("niveaux", NIVEAUX.map(x => x[0]));
  // Un type de contrat apparu depuis la mémorisation (ex. « Stage ») arrive coché : sinon ses offres
  // disparaîtraient en silence pour qui avait déjà réglé ses filtres. Les anciens mémos, sans
  // « contrats_vus », connaissaient les six familles d'avant le stage.
  const vus = memoA("contrats_vus", ["cdi", "cdd", "alt", "mis", "indep", "autre"]);
  document.querySelectorAll("#f-contrats input").forEach(i => { i.checked = memoC.includes(i.value) || !vus.includes(i.value); });
  document.querySelectorAll("#f-niveaux input").forEach(i => { i.checked = memoN.includes(i.value); });
  const memoS = memoA("sources", null);
  document.querySelectorAll("#f-sources input").forEach(i => { i.checked = !memoS || memoS.includes(i.value); });
}

/* La barre d'onglets, avec le nombre d'offres actives de chacun ; masquée s'il n'y en a qu'un. */
function poserBarreOnglets() {
  const barre = document.getElementById("onglets");
  if (!barre) return;
  barre.innerHTML = Commun.onglets.map(o => {
    const codes = new Set(o.groupes.flatMap(g => g.codes));
    const n = D.offres.filter(x => codes.has(x.rome)).length;
    return `<button type="button" role="tab" data-onglet="${o.id}" aria-selected="false">${o.titre} <small>${n}</small></button>`;
  }).join("");
  barre.hidden = Commun.onglets.length < 2;
  const choisir = b => { if (b && b.dataset.onglet !== Commun.onglet.id) { poserOnglet(b.dataset.onglet); Commun.rafraichir(); } };
  barre.addEventListener("click", e => choisir(e.target.closest("[role=tab]")));
  // Flèches gauche/droite : on passe d'un onglet au voisin, comme dans tout jeu d'onglets.
  barre.addEventListener("keydown", e => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const bs = [...barre.querySelectorAll("[role=tab]")], i = bs.findIndex(b => b.dataset.onglet === Commun.onglet.id);
    const b = bs[(i + (e.key === "ArrowRight" ? 1 : bs.length - 1)) % bs.length];
    b.focus(); choisir(b);
  });
}

/* ============================================================
   6) CHARGEMENT ET BOUCLE DE RENDU
   ============================================================ */
const Commun = {
  D: null,          // les données, une fois chargées
  f: null,          // l'état des filtres au dernier rendu
  lib: {},          // code ROME -> { libelle, groupe, … }
  onglets: [],      // les onglets du resume.json
  onglet: null,     // l'onglet affiché : { id, titre, groupes }
  groupeDe: {},     // code ROME -> nom de son groupe dans l'onglet affiché
  memo: null,       // les filtres mémorisés, par onglet
  rendre: null,     // le dessinateur de la page

  /* Tout ce qui est commun à chaque rendu : compteurs des cases, ligne de
     synthèse, mémorisation, puis la page dessine ses propres graphiques. */
  rafraichir() {
    const f = etatFiltres();
    Commun.f = f;
    const parMetier = D.offres.filter(o => f.metiers.has(o.rome));           // base des compteurs de filtres
    const offres = filtrer(f);
    const n = offres.length, total = D.offres.filter(o => o.rome in Commun.groupeDe).length;
    const titre = Commun.onglets.length > 1 ? ` « ${Commun.onglet.titre} »` : "";

    // Compteurs dans les cases de filtre + ligne de synthèse
    CONTRATS.forEach(([k]) => { const e = document.getElementById("nb-c-" + k); if (e) e.textContent = parMetier.filter(o => familleContrat(o) === k).length; });
    NIVEAUX.forEach(([k]) => { const e = document.getElementById("nb-n-" + k); if (e) e.textContent = parMetier.filter(o => niv(o) === k).length; });
    document.querySelectorAll("#f-sources input").forEach(i => { const e = i.parentNode.querySelector("small"); if (e) e.textContent = parMetier.filter(o => sourceDe(o) === i.value).length; });
    document.getElementById("compte").innerHTML = `<b>${n}</b> offre${n > 1 ? "s" : ""} sélectionnée${n > 1 ? "s" : ""} sur ${total}${titre ? " de l'onglet" + titre : ""} — ${f.metiers.size} métier${f.metiers.size > 1 ? "s" : ""} coché${f.metiers.size > 1 ? "s" : ""}.`;
    document.getElementById("aucune").hidden = n > 0;
    const resume = document.getElementById("resume-filtres");
    if (resume) resume.textContent = `Filtres${titre} (${f.metiers.size} métier${f.metiers.size > 1 ? "s" : ""}, ${n} offre${n > 1 ? "s" : ""})`;
    // Plus rien de sélectionné : le message dit « recochez un métier », le panneau replié
    // doit donc s'ouvrir. Sinon la page réclame une action dont elle cache les cases.
    if (n === 0) { const d = document.querySelector("details.carte"); if (d) d.open = true; }

    // Mémorisation des trois filtres de l'onglet, et de l'onglet lui-même : ils suivent d'une page à l'autre.
    Commun.memo.par_onglet[Commun.onglet.id] = { metiers: [...f.metiers], contrats: [...f.contrats], niveaux: [...f.niveaux],
      contrats_vus: CONTRATS.map(x => x[0]), sources: f.sources ? [...f.sources] : undefined };
    try { localStorage.setItem("metiers-filtres", JSON.stringify(Commun.memo)); } catch (e) {}

    Commun.rendre(offres, D);
  },

  /* rendre(offres, D) : rappelée au chargement puis à chaque changement de filtre.
     initier(D) : facultatif, une seule fois, avant le premier rendu. */
  demarrer(rendre, initier) {
    Commun.rendre = rendre;
    poserNavEtFiltres();
    // GitHub Pages met le JSON en cache 10 minutes : on le redemande frais à chaque chargement.
    fetch("data/resume.json", { cache: "no-cache" }).then(r => r.json()).then(d => {
      if (!d.metiers || !d.offres) throw new Error("ancien format de resume.json — rechargez la page (Ctrl+F5)");
      D = d;
      Commun.D = d;
      Commun.lib = Object.fromEntries(d.metiers.map(m => [m.code, m]));
      if (Array.isArray(d.niveaux) && d.niveaux.length) NIVEAUX = d.niveaux.filter(x => Array.isArray(x) && x.length === 2);
      if (Array.isArray(d.formations) && d.formations.length) FORMATIONS = d.formations;

      // Dernière collecte de chaque source ; une source qui a plus de trois jours de retard est signalée.
      const collectes = Object.entries(d.collectes || { [d.source]: d.date });
      const enRetard = collectes.filter(([, j]) => (Date.now() - Date.parse(j)) / 86400000 > 3);
      const sous = document.getElementById("sous");
      if (sous) sous.innerHTML =
        `${d.requete} · dernière collecte : ${collectes.map(([s, j]) => `${s} <b>${dateFr(j)}</b>`).join(", ")} · ${d.offres.length} offres actives, ${d.versions_conservees} versions d'annonces conservées`
        + (enRetard.length ? `<span class="alerte">Attention : ${enRetard.map(([s, j]) => `${s} n'a pas été mis à jour depuis le ${dateFr(j)}`).join(" ; ")}. Des offres affichées peuvent avoir expiré entre-temps.</span>` : "");

      // --- Cases des filtres type de contrat et niveau de poste (cochées par poserOnglet) ---
      document.getElementById("f-contrats").innerHTML = CONTRATS.map(([k, l]) =>
        `<label><input type="checkbox" value="${k}"> ${l} <small id="nb-c-${k}"></small></label>`).join("");
      document.getElementById("f-niveaux").innerHTML = NIVEAUX.map(([k, l]) =>
        `<label><input type="checkbox" value="${k}"> <i class="pastille" style="background:${COUL_NIV[k]}"></i> ${l} <small id="nb-n-${k}"></small></label>`).join("");
      // Sources : France Travail, et les autres sources une fois branchées (resume.json, clé « sources »).
      const sources = Array.isArray(d.sources) && d.sources.length ? d.sources : [SOURCE_DEFAUT];
      document.getElementById("f-sources").innerHTML = sources.map(s =>
        `<label><input type="checkbox" value="${s}"> <i class="pastille" style="background:${couleurSource(s)}"></i> ${s} <small></small></label>`).join("");
      document.getElementById("bloc-sources").hidden = sources.length < 2;

      // --- Événements, posés une fois : les cases de métiers et de groupes changent avec l'onglet ---
      document.getElementById("metiers").addEventListener("change", () => { majGroupes(); Commun.rafraichir(); });
      // Une case par groupe : cocher/décocher le groupe entier, cumulables.
      document.getElementById("groupes").addEventListener("change", e => {
        const c = e.target.closest("[data-groupe-case]");
        if (!c) return;
        document.querySelectorAll(`#metiers input[data-groupe="${c.dataset.groupeCase}"]`).forEach(i => { i.checked = c.checked; });
        majGroupes(); Commun.rafraichir();
      });
      document.querySelectorAll(".boutons button").forEach(b => b.addEventListener("click", () => {
        document.querySelectorAll("#metiers input").forEach(i => { i.checked = b.dataset.groupe === "tous"; });
        majGroupes(); Commun.rafraichir();
      }));
      document.getElementById("f-contrats").addEventListener("change", Commun.rafraichir);
      document.getElementById("f-niveaux").addEventListener("change", Commun.rafraichir);
      document.getElementById("f-sources").addEventListener("change", Commun.rafraichir);

      // --- Onglets : le dernier consulté, sinon le premier ---
      Commun.onglets = ongletsDe(d);
      Commun.memo = lireMemo(Commun.onglets);
      poserBarreOnglets();
      poserOnglet(Commun.memo.onglet);

      if (initier) initier(d);
      Commun.rafraichir();
    }).catch(e => { const s = document.getElementById("sous"); if (s) s.textContent = "Impossible de lire data/resume.json : " + e; });
  },
};
