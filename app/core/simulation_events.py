"""
Événements de la simulation d'emploi.
Chaque événement a :
  - description
  - type : "present" | "absent"  (pour générer Presence ou Absence)
  - statut_final : "actif" | "vire"
"""

from typing import TypedDict

class Event(TypedDict):
    description: str
    type: str          # "present" | "absent"
    statut_final: str  # "actif" | "vire"


# ---------------------------------------------------------------------------
# BOSS
# ---------------------------------------------------------------------------
BOSS_ACTIF: list[Event] = [
    {"description": "Le responsable remarque que l'employé a rapidement compris l'organisation de l'entreprise et lui confie la coordination d'une petite équipe.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé propose une nouvelle organisation des tâches. L'idée est intéressante et sera testée pendant quelques jours.", "type": "present", "statut_final": "actif"},
    {"description": "Une réunion importante est organisée et l'employé présente clairement les problèmes rencontrés par l'équipe.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé résout rapidement un conflit entre deux collègues et permet à l'équipe de reprendre son travail normalement.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé identifie une erreur dans le planning et la corrige avant qu'elle ne provoque un problème.", "type": "present", "statut_final": "actif"},
    {"description": "Une journée particulièrement chargée oblige l'employé à gérer plusieurs problèmes en même temps, mais tout se termine correctement.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé prend une bonne décision concernant l'organisation du personnel et reçoit les félicitations du responsable.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé demande l'avis de son équipe avant de prendre une décision importante, ce qui améliore la coordination.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé arrive en retard à une réunion importante. Le responsable lui rappelle que la ponctualité est importante pour son poste.", "type": "present", "statut_final": "actif"},
    {"description": "Une décision prise trop rapidement crée une petite confusion dans l'équipe. L'employé corrige immédiatement la situation.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé passe une partie de la journée à vérifier les dossiers administratifs et découvre plusieurs petites erreurs.", "type": "present", "statut_final": "actif"},
    {"description": "L'équipe atteint ses objectifs de la journée et le responsable considère que l'employé s'intègre correctement.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé est absent pour une raison personnelle, mais prévient l'entreprise suffisamment tôt pour permettre une réorganisation.", "type": "absent", "statut_final": "actif"},
    {"description": "L'employé revient après son absence et reprend normalement ses responsabilités.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé tente d'imposer une nouvelle règle sans consulter les autres responsables. Le projet est finalement abandonné.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé prend une décision qui entraîne une petite erreur d'organisation. Le problème est corrigé dans la journée.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé ne se présente pas au travail et ne prévient personne. L'équipe doit se débrouiller sans lui.", "type": "absent", "statut_final": "actif"},
    {"description": "L'employé réussit à calmer une situation tendue avec un client important.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé découvre qu'une équipe manque de matériel et organise rapidement une solution temporaire.", "type": "present", "statut_final": "actif"},
    {"description": "Après plusieurs bonnes décisions, l'employé gagne progressivement la confiance de l'équipe.", "type": "present", "statut_final": "actif"},
]

BOSS_VIRE: list[Event] = [
    {"description": "L'employé prend une décision importante sans vérifier les informations disponibles. Une erreur coûte du temps à l'entreprise.", "type": "present", "statut_final": "vire"},
    {"description": "Plusieurs collègues signalent que l'employé donne des ordres contradictoires et désorganise le travail.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé s'absente plusieurs fois sans justification et laisse régulièrement l'équipe sans responsable.", "type": "absent", "statut_final": "vire"},
    {"description": "Une erreur importante dans l'organisation provoque l'annulation d'une activité. Le responsable décide de mettre fin à la collaboration.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé refuse systématiquement de suivre les décisions de la direction et continue d'imposer ses propres méthodes.", "type": "present", "statut_final": "vire"},
    {"description": "Après plusieurs avertissements, l'employé continue de négliger les responsabilités liées à son poste.", "type": "present", "statut_final": "vire"},
    {"description": "Le responsable constate que l'employé n'arrive pas à gérer la pression du poste et décide d'arrêter la période d'essai.", "type": "present", "statut_final": "vire"},
    {"description": "Une absence non justifiée oblige l'entreprise à annuler une réunion importante. Le responsable met fin à la période d'essai.", "type": "absent", "statut_final": "vire"},
]

# ---------------------------------------------------------------------------
# VENDEUR
# ---------------------------------------------------------------------------
VENDEUR_ACTIF: list[Event] = [
    {"description": "L'employé accueille correctement les premiers clients et apprend rapidement à présenter les produits.", "type": "present", "statut_final": "actif"},
    {"description": "Une cliente demande un conseil compliqué. L'employé prend le temps d'écouter et propose une solution adaptée.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé réalise plusieurs ventes dans la journée et commence à prendre confiance.", "type": "present", "statut_final": "actif"},
    {"description": "Une journée calme permet à l'employé de réorganiser les rayons et de vérifier les stocks.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé remarque qu'un produit est presque épuisé et prévient le responsable avant la rupture de stock.", "type": "present", "statut_final": "actif"},
    {"description": "Un client mécontent arrive au magasin. L'employé reste calme et réussit à trouver une solution.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé apprend rapidement le fonctionnement de la caisse et commet très peu d'erreurs.", "type": "present", "statut_final": "actif"},
    {"description": "Les ventes de la journée sont meilleures que prévu et le responsable félicite l'employé.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé aide un collègue à ranger une livraison arrivée en retard.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé conseille honnêtement un client qui hésite entre plusieurs produits.", "type": "present", "statut_final": "actif"},
    {"description": "Une petite erreur de prix est détectée sur une commande. L'employé la signale immédiatement et la corrige.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé arrive légèrement en retard mais prévient le responsable et reste jusqu'à la fin de son service.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé est absent pour cause de maladie et prévient le magasin avant le début de son service.", "type": "absent", "statut_final": "actif"},
    {"description": "L'employé revient après son absence et reprend son travail normalement.", "type": "present", "statut_final": "actif"},
    {"description": "Une livraison importante arrive. L'employé aide à vérifier les produits et à les placer correctement.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé ne comprend pas immédiatement le fonctionnement d'un nouveau produit, mais prend le temps de se former.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé réussit à convaincre plusieurs clients grâce à une présentation claire des produits.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé oublie de remettre un rayon en ordre, puis corrige son erreur après le rappel du responsable.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé ne vient pas travailler à cause d'un problème de transport et prévient le magasin.", "type": "absent", "statut_final": "actif"},
    {"description": "L'employé aide un client à trouver un produit que personne d'autre ne parvenait à localiser.", "type": "present", "statut_final": "actif"},
]

VENDEUR_VIRE: list[Event] = [
    {"description": "Plusieurs erreurs de caisse sont constatées malgré les rappels du responsable.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé quitte son poste pendant une période chargée sans prévenir ses collègues, ce qui provoque une file d'attente importante.", "type": "present", "statut_final": "vire"},
    {"description": "Plusieurs clients se plaignent du comportement de l'employé et le responsable décide de mettre fin à la période d'essai.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé s'absente sans prévenir et oblige un collègue à venir travailler au dernier moment.", "type": "absent", "statut_final": "vire"},
    {"description": "Une erreur importante de caisse n'est pas signalée et crée un problème lors de la fermeture du magasin.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé refuse de suivre les procédures de sécurité du magasin malgré plusieurs rappels.", "type": "present", "statut_final": "vire"},
    {"description": "Les performances commerciales restent très faibles malgré plusieurs jours de formation et d'accompagnement.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé donne volontairement une mauvaise information à plusieurs clients. Le responsable décide d'arrêter la collaboration.", "type": "present", "statut_final": "vire"},
    {"description": "Une absence répétée et non justifiée désorganise le planning du magasin. La période d'essai est interrompue.", "type": "absent", "statut_final": "vire"},
]

# ---------------------------------------------------------------------------
# NETTOYEUR DE TOILETTES
# ---------------------------------------------------------------------------
NETTOYEUR_ACTIF: list[Event] = [
    {"description": "L'employé découvre les locaux et apprend les procédures de nettoyage et de sécurité.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé réalise sa première tournée correctement et signale qu'un distributeur de savon est presque vide.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé connaît déjà mieux les locaux et termine sa tournée plus rapidement que la veille.", "type": "present", "statut_final": "actif"},
    {"description": "Une zone particulièrement difficile demande plus de temps, mais l'employé réussit à la nettoyer correctement.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé remarque une fuite dans un sanitaire et prévient immédiatement le responsable.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé aide à réorganiser le matériel d'entretien afin de rendre la tournée plus efficace.", "type": "present", "statut_final": "actif"},
    {"description": "Une journée très chargée oblige l'employé à effectuer plusieurs passages supplémentaires dans les sanitaires.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé reçoit un rappel concernant l'utilisation correcte d'un produit d'entretien et applique immédiatement les consignes.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé arrive un peu en retard mais prévient le responsable et termine correctement sa tournée.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé est absent pour cause de maladie et prévient l'entreprise avant son horaire de travail.", "type": "absent", "statut_final": "actif"},
    {"description": "L'employé revient après une journée d'absence et reprend normalement son travail.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé nettoie accidentellement une zone avec le mauvais produit, mais signale immédiatement son erreur.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé constate qu'une zone est particulièrement sale après une activité et décide de la nettoyer sans attendre.", "type": "present", "statut_final": "actif"},
    {"description": "Le responsable remarque que l'employé travaille avec sérieux et respecte les horaires prévus.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé aide un collègue à transporter du matériel avant de commencer sa propre tournée.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé oublie une petite zone pendant sa tournée, mais retourne la nettoyer après le rappel du responsable.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé ne vient pas travailler pour un rendez-vous personnel et prévient l'entreprise suffisamment tôt.", "type": "absent", "statut_final": "actif"},
    {"description": "Une panne d'eau perturbe le nettoyage. L'employé adapte son travail et attend les instructions du responsable.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé termine sa tournée plus tôt que prévu et aide à vérifier les stocks de produits.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé signale plusieurs problèmes dans les sanitaires et permet au responsable de les faire réparer rapidement.", "type": "present", "statut_final": "actif"},
]

NETTOYEUR_VIRE: list[Event] = [
    {"description": "L'employé utilise à plusieurs reprises les produits d'entretien sans respecter les consignes de sécurité malgré plusieurs rappels.", "type": "present", "statut_final": "vire"},
    {"description": "Plusieurs zones sont régulièrement oubliées et le responsable doit demander à d'autres employés de terminer le travail.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé ne vient pas travailler sans prévenir et laisse toute sa tournée à ses collègues.", "type": "absent", "statut_final": "vire"},
    {"description": "Une absence non justifiée se répète alors que le responsable avait déjà demandé davantage de régularité.", "type": "absent", "statut_final": "vire"},
    {"description": "L'employé refuse de respecter les règles de sécurité concernant les produits chimiques malgré plusieurs avertissements.", "type": "present", "statut_final": "vire"},
    {"description": "Le responsable constate que le travail doit être systématiquement refait par d'autres employés. La période d'essai est interrompue.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé endommage du matériel en ne respectant pas les procédures et ne signale pas immédiatement l'incident.", "type": "present", "statut_final": "vire"},
    {"description": "Les retards et absences deviennent trop fréquents pour permettre une organisation correcte du service.", "type": "absent", "statut_final": "vire"},
]

# ---------------------------------------------------------------------------
# GÉNÉRAUX (compatibles avec n'importe quel poste)
# ---------------------------------------------------------------------------
GENERAL_ACTIF: list[Event] = [
    # --- déjà présents (conservés) ---
    {"description": "L'employé s'adapte rapidement à son nouvel environnement de travail et pose les bonnes questions.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé aide spontanément un collègue qui rencontre une difficulté.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé est absent pour cause de maladie et prévient son responsable avant le début de la journée.", "type": "absent", "statut_final": "actif"},
    {"description": "L'employé revient après son absence et reprend normalement son activité.", "type": "present", "statut_final": "actif"},
    {"description": "Un problème matériel ralentit le travail pendant une partie de la journée, mais l'équipe trouve une solution.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé reçoit un rappel concernant une procédure interne et promet de faire plus attention.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé arrive en retard à cause d'un problème de transport mais prévient son responsable.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé réalise une très bonne journée et reçoit des félicitations.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé demande une journée d'absence pour une raison personnelle et prévient suffisamment tôt.", "type": "absent", "statut_final": "actif"},
    # --- nouveaux (universels, tout métier) ---
    {"description": "L'employé prend le temps de lire les consignes de sécurité et de les appliquer correctement dès le premier jour.", "type": "present", "statut_final": "actif"},
    {"description": "Un collègue explique une procédure : l'employé écoute attentivement et la reproduit sans erreur.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé signale un petit dysfonctionnement avant qu'il ne devienne un vrai problème.", "type": "present", "statut_final": "actif"},
    {"description": "La journée est calme : l'employé en profite pour ranger son espace de travail et anticiper le lendemain.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé accepte de rester un peu plus longtemps pour terminer une tâche urgente, sans se plaindre.", "type": "present", "statut_final": "actif"},
    {"description": "Lors d'une réunion d'équipe, l'employé partage une observation utile qui améliore l'organisation du service.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé se trompe sur une consigne mineure, le reconnaît et corrige immédiatement.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé arrive à l'heure malgré un embouteillage inhabituel et commence sa journée sereinement.", "type": "present", "statut_final": "actif"},
    {"description": "Un nouveau logiciel / outil est mis en place : l'employé se forme rapidement et aide les autres ensuite.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé gère correctement une situation imprévue sans paniquer ni bloquer le reste de l'équipe.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé respecte les pauses et revient exactement à l'heure prévue.", "type": "present", "statut_final": "actif"},
    {"description": "Un client ou un collègue remercie l'employé pour sa disponibilité et sa politesse.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé prévient à l'avance d'un rendez-vous médical et s'absente une demi-journée uniquement.", "type": "absent", "statut_final": "actif"},
    {"description": "L'employé propose une petite amélioration pratique (rangement, check-list, rappel) qui est adoptée par l'équipe.", "type": "present", "statut_final": "actif"},
    {"description": "Après un jour difficile, l'employé revient le lendemain motivé et concentré.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé vérifie deux fois son travail avant de le valider et évite ainsi une erreur coûteuse.", "type": "present", "statut_final": "actif"},
    {"description": "Une formation interne a lieu : l'employé y participe activement et pose des questions pertinentes.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé partage équitablement les tâches pénibles avec ses collègues sans se faire prier.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé est légèrement en retard mais rattrape le temps perdu en restant plus efficace le reste de la journée.", "type": "present", "statut_final": "actif"},
    {"description": "L'employé note soigneusement les consignes reçues et n'a plus besoin de les redemander.", "type": "present", "statut_final": "actif"},
]

GENERAL_VIRE: list[Event] = [
    # --- déjà présents (conservés) ---
    {"description": "Plusieurs absences non justifiées et répétées désorganisent l'équipe. Le responsable décide de mettre fin à la période d'essai.", "type": "absent", "statut_final": "vire"},
    {"description": "Après plusieurs avertissements, l'employé continue de ne pas respecter les procédures internes.", "type": "present", "statut_final": "vire"},
    {"description": "Une erreur importante est répétée malgré plusieurs rappels du responsable.", "type": "present", "statut_final": "vire"},
    {"description": "Le comportement de l'employé crée des conflits répétés avec les autres membres de l'équipe.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé ne se présente pas à plusieurs reprises sans justification et l'organisation du service devient impossible.", "type": "absent", "statut_final": "vire"},
    {"description": "Le responsable estime que le poste ne correspond finalement pas au profil de l'employé et met fin à la période d'essai.", "type": "present", "statut_final": "vire"},
    # --- nouveaux (universels) ---
    {"description": "L'employé refuse systématiquement d'appliquer les consignes de sécurité malgré les rappels.", "type": "present", "statut_final": "vire"},
    {"description": "Des retards répétés et non justifiés perturbent le démarrage de chaque journée de travail.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé abandonne une tâche en cours sans prévenir personne, ce qui bloque le reste de l'équipe.", "type": "present", "statut_final": "vire"},
    {"description": "Après plusieurs jours, le responsable constate que l'employé ne progresse pas et ne montre aucun engagement.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé ment sur une absence puis est confondu. La confiance est rompue.", "type": "absent", "statut_final": "vire"},
    {"description": "Des plaintes récurrentes de collègues ou de clients concernant le comportement de l'employé obligent à arrêter la collaboration.", "type": "present", "statut_final": "vire"},
    {"description": "L'employé utilise du matériel de façon dangereuse ou négligente malgré les formations reçues.", "type": "present", "statut_final": "vire"},
    {"description": "Une absence le jour d'une échéance importante, sans aucun message, force le responsable à interrompre la période d'essai.", "type": "absent", "statut_final": "vire"},
]


EVENTS_BY_POSTE = {
    "Boss": {"actif": BOSS_ACTIF, "vire": BOSS_VIRE},
    "Vendeur": {"actif": VENDEUR_ACTIF, "vire": VENDEUR_VIRE},
    "Nettoyeur de toilettes": {"actif": NETTOYEUR_ACTIF, "vire": NETTOYEUR_VIRE},
}
