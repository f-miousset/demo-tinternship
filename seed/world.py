"""The fictional world the demo is seeded with.

Everything here is invented: the candidate, the school, every company, every
person and every link (all under `example.com`). Nothing was produced by a
model — it is written by hand so that the demo can show what the agents *would*
return without ever calling one.

`scripts/build_seed.py` feeds this through the real backend (the copy in
`app/backend`) to produce the JSON the browser mock serves, so the shapes are
the backend's own rather than a re-implementation of them.

Days are offsets before the seed's epoch. The browser shifts every timestamp at
first visit so the demo always reads as "recent", however long after the build
it is opened.
"""

from __future__ import annotations

EPOCH = "2026-10-08T09:00:00+00:00"

# ---------------------------------------------------------------------------
# The candidate
# ---------------------------------------------------------------------------

PROFILE = {
    "full_name": "Alex Martin",
    "headline": "MSc Data Science student — machine learning, forecasting, NLP",
    "email": "alex.martin@example.org",
    "phone": "+33 6 00 00 00 00",
    "location": "Paris, France",
    "linkedin_url": "https://www.example.com/in/alex-martin-demo",
    "github_url": "https://code.example.com/alex-martin-demo",
    "portfolio_url": "",
    "summary": (
        "Second-year MSc Data Science student looking for a six-month end-of-studies "
        "internship from February 2027. Built forecasting and NLP models in a utility "
        "internship and two research projects; most at home where a model has to be "
        "explained to the people who use it."
    ),
    "experiences": [
        {
            "title": "Data Analyst Intern",
            "organisation": "Brightwater Utilities",
            "location": "Lyon, France",
            "start_date": "2025-06",
            "end_date": "2025-08",
            "description": "Analytics team of a regional water utility.",
            "highlights": [
                "Built a gradient-boosted daily demand forecast for 40 pumping stations (MAPE 6.1% → 4.3%)",
                "Automated the weekly leak-suspicion report in Python and SQL, saving ~4 h/week",
                "Presented the forecast's failure cases to the operations team",
            ],
            "skills": ["Python", "LightGBM", "SQL", "Power BI"],
        },
        {
            "title": "Teaching Assistant, Statistics",
            "organisation": "École Supérieure des Données",
            "location": "Paris, France",
            "start_date": "2025-09",
            "end_date": "",
            "description": "Weekly lab sessions for 30 first-year students.",
            "highlights": ["Wrote the R and Python lab notebooks used by three groups"],
            "skills": ["R", "Python", "Teaching"],
        },
    ],
    "education": [
        {
            "degree": "MSc Data Science",
            "institution": "École Supérieure des Données (ESD)",
            "location": "Paris, France",
            "start_date": "2025",
            "end_date": "2027",
            "details": "Machine learning track. Thesis topic: uncertainty in short-term load forecasting.",
            "coursework": ["Statistical learning", "Deep learning", "Time series", "Optimisation"],
        },
        {
            "degree": "BSc Applied Mathematics",
            "institution": "Université Rive-Gauche",
            "location": "Lyon, France",
            "start_date": "2022",
            "end_date": "2025",
            "details": "Graduated with honours.",
            "coursework": [],
        },
    ],
    "projects": [
        {
            "name": "Clinical note de-identification",
            "description": "Fine-tuned a French token-classification model to mask names and dates in synthetic clinical notes.",
            "url": "",
            "highlights": ["F1 0.94 on a held-out synthetic set"],
            "technologies": ["PyTorch", "Hugging Face Transformers"],
        },
        {
            "name": "Bike-share rebalancing",
            "description": "Mixed-integer model choosing overnight truck routes for a simulated 120-station network.",
            "url": "",
            "highlights": ["Cut simulated empty-station hours by 31%"],
            "technologies": ["Python", "OR-Tools"],
        },
    ],
    "skills": [
        "Python", "SQL", "PyTorch", "scikit-learn", "LightGBM", "pandas", "Docker",
        "Git", "Time-series forecasting", "NLP", "Optimisation", "Power BI", "R",
    ],
    "languages": [
        {"language": "French", "level": "Native"},
        {"language": "English", "level": "C1"},
        {"language": "Spanish", "level": "B1"},
    ],
    "certifications": [],
    "awards": ["Second place, ESD forecasting challenge 2026"],
    "interests": ["Climbing", "Urban cycling", "Board games"],
    "extraction_notes": "",
}

# The two lists the résumé's coursework and skills blanks are filled from.
# Each item carries a set of tags so a posting can pick the relevant ones.
COURSES = [
    ("Statistical learning", "Apprentissage statistique", {"ml", "all"}),
    ("Deep learning", "Apprentissage profond", {"ml", "nlp", "vision"}),
    ("Time series analysis", "Analyse de séries temporelles", {"forecast", "energy", "finance"}),
    ("Natural language processing", "Traitement automatique des langues", {"nlp"}),
    ("Operations research and combinatorial optimisation", "Recherche opérationnelle et optimisation combinatoire", {"or", "logistics"}),
    ("Bayesian statistics", "Statistique bayésienne", {"forecast", "finance", "ml"}),
    ("Databases and distributed systems", "Bases de données et systèmes distribués", {"data_eng", "analytics"}),
    ("Spatial statistics", "Statistique spatiale", {"geo", "energy"}),
]

SKILLS = [
    ("Python", "Python", {"all"}),
    ("SQL", "SQL", {"all"}),
    ("PyTorch", "PyTorch", {"ml", "nlp", "vision"}),
    ("scikit-learn", "scikit-learn", {"ml", "forecast", "analytics"}),
    ("LightGBM", "LightGBM", {"forecast", "energy", "finance"}),
    ("Hugging Face Transformers", "Hugging Face Transformers", {"nlp"}),
    ("OR-Tools", "OR-Tools", {"or", "logistics"}),
    ("Docker", "Docker", {"data_eng", "ml"}),
    ("Power BI", "Power BI", {"analytics"}),
    ("GeoPandas", "GeoPandas", {"geo"}),
    ("A/B testing", "Tests A/B", {"analytics"}),
    ("Time-series forecasting", "Prévision de séries temporelles", {"forecast", "energy"}),
]

# ---------------------------------------------------------------------------
# The search brief and the playbook — what steps 2–4 of Account produce
# ---------------------------------------------------------------------------

BRIEF = {
    "headline": "Six-month end-of-studies data science / ML internship in Paris or Lyon from February 2027",
    "role_titles": [
        "Data Scientist Intern", "Machine Learning Intern", "Stage Data Scientist",
        "Stage de fin d'études Machine Learning", "NLP Intern",
    ],
    "domain": "Applied machine learning — forecasting, NLP, optimisation",
    "seniority": "internship",
    "start_date": "2027-02-01",
    "end_date": "2027-08-31",
    "duration": "6 months",
    "locations": ["Paris", "Lyon", "Remote within France"],
    "remote_preference": "hybrid",
    "relocation": "Open to Lyon; elsewhere only for an exceptional fit",
    "work_authorisation": "EU citizen — no sponsorship needed",
    "languages": ["French (native)", "English (C1)"],
    "company_profile": "Scale-ups and mid-size companies with a real data team; energy and health especially",
    "target_companies": ["Helio Grid", "Nimbus Labs", "Orbe Santé"],
    "excluded_companies": [],
    "must_haves": ["Six-month end-of-studies internship (convention de stage)", "Hands-on modelling, not only dashboards"],
    "nice_to_haves": ["Energy or climate domain", "Mentoring by a senior data scientist", "Model in production by the end"],
    "deal_breakers": ["Unpaid", "Pure reporting role"],
    "skills": ["Python", "SQL", "PyTorch", "LightGBM", "Time-series forecasting", "NLP"],
    "compensation_expectation": "At least the legal minimum gratification; ideally €1,300+/month",
    "education": "MSc Data Science, École Supérieure des Données, second year",
    "portfolio_links": [],
    "search_keywords": [
        "stage data scientist 6 mois février 2027", "machine learning intern Paris",
        "stage prévision énergie Lyon", "NLP internship France",
    ],
    "open_questions": ["Would a research-lab internship count, if it ends in a publication rather than a product?"],
    "confidence": "high",
}

PLAYBOOK = {
    "summary": (
        "French end-of-studies data internships are filled from October to January for "
        "February starts. Recruiters screen for one modelling project with a measurable "
        "result, the convention dates, and the posting's own tool names. A short, "
        "specific letter still matters at scale-ups; large groups rarely read it."
    ),
    "domain_insights": [
        "Energy and utility data teams value forecasting error metrics stated plainly (MAPE, pinball loss).",
        "Health-data roles ask early about data protection — mention de-identification work up front.",
        "Scale-ups often run a take-home exercise instead of a technical interview; budget an evening.",
    ],
    "hiring_timeline": "Postings for February starts open mid-September and peak in November; most close by mid-January.",
    "where_to_search": [
        "Company career pages (most scale-ups post there first)",
        "School job board and alumni network",
        "Specialised data and ML job boards",
    ],
    "search_query_patterns": [
        '"stage" "data scientist" "février 2027"',
        '"machine learning intern" Paris 2027',
        '"stage de fin d\'études" prévision',
    ],
    "resume_guidance": [
        "Lead with the forecast that cut error by a third — it is the most specific result you have.",
        "Name the exact libraries the posting names, where they are true.",
        "One page, no photo, start date and duration in the header.",
    ],
    "ats_keywords": ["Python", "SQL", "machine learning", "forecasting", "time series", "PyTorch", "NLP", "data pipeline"],
    "cover_letter_guidance": [
        "Three short paragraphs: why them, one proof, availability.",
        "Quote something specific the team has published or shipped.",
    ],
    "interview_expectations": [
        "A walk-through of one project with its failure cases.",
        "A live SQL or pandas exercise at most data teams.",
        "A question about how you would explain a model to a non-technical stakeholder.",
    ],
    "outreach_strategy": [
        "Message the data lead with one sentence on their published work, not a CV.",
        "Ask alumni at the company for a 15-minute call before applying.",
    ],
    "common_mistakes": [
        "A generic letter that could be sent to any company.",
        "Listing every library ever touched instead of the ones that matter for this role.",
    ],
    "red_flags_in_postings": [
        "No named team or manager.",
        "\"Data intern\" whose missions are all reporting and slide-making.",
    ],
    "extra_sections": [],
    "sources": [
        {"title": "Internship hiring calendar (illustrative)", "url": "https://www.example.com/guides/internship-calendar", "takeaway": "Peak posting month is November for February starts."},
        {"title": "What data teams screen for (illustrative)", "url": "https://www.example.com/guides/data-screening", "takeaway": "One measurable project beats a long tool list."},
    ],
}

# The interview that produced the brief (Account → step 2). Replayed by the
# mock after "Start over": each focus on the box fills the next answer.
INTERVIEW = [
    ("assistant", "I've read your profile — MSc Data Science at ESD, a forecasting internship at Brightwater Utilities, and an NLP project on clinical notes. Let's pin down the internship you want. When can you start, and for how long?"),
    ("user", "February 2027, for six months — it's my end-of-studies internship."),
    ("assistant", "Got it: a six-month *stage de fin d'études* from February. Where would you work — and is remote or hybrid important?"),
    ("user", "Paris or Lyon, ideally hybrid. I'd move to Lyon for the right team."),
    ("assistant", "Which kind of work would make you say yes immediately — and which would make you say no?"),
    ("user", "Yes to real modelling, especially forecasting or NLP, ideally in energy or health. No to a role that's only dashboards and reporting."),
    ("assistant", "That's clear. Last one: any companies you're already watching, or any to avoid?"),
    ("user", "I'm watching Helio Grid, Nimbus Labs and Orbe Santé. Nothing to avoid."),
    ("assistant", "Thanks — I have what I need. I'll write your search brief now; the HR Expert will research how these internships are hired from it."),
]

# ---------------------------------------------------------------------------
# Postings
# ---------------------------------------------------------------------------
#
# `tags` pick the coursework and skills a résumé run would choose, and pick
# which canned sentences the letter uses. `why` / `proof` are the two
# job-specific halves of the letter's opening and middle paragraphs.
# `pool` decides where a posting starts:
#   deck       — on the Jobs deck
#   discarded  — in the deck's discard pile
#   app:<n>    — an application (see APPLICATIONS)
#   search:<k> — revealed by the canned Jobs-chat search <k>
#   link / text — revealed by the canned paste of a link / of a posting's text


def _job(**fields):
    defaults = {
        "remote": "hybrid",
        "source": "google_search",
        "contract_type": "internship",
        "start_date": "February 2027",
        "duration": "6 months",
        "language": "en",
        "confidence": "high",
        "url_status": "ok",
        "url_http_status": 200,
        "nice_to_have": [],
        "deadline": "",
    }
    return {**defaults, **fields}


JOBS = [
    _job(
        key="helio", pool="app:helio", company="Helio Grid", title="Data Scientist Intern — Energy Forecasting",
        title_fr="Stagiaire Data Scientist — Prévision énergétique",
        location="Lyon, France", posted_days_ago=23, discovered_days_ago=21,
        url="https://careers.example.com/helio-grid/data-scientist-intern-forecasting",
        summary="Six months on the day-ahead solar and load forecasts that dispatch Helio Grid's battery fleet.",
        description=(
            "Helio Grid operates 140 MWh of grid batteries across the Rhône valley. The forecasting team "
            "(four data scientists) owns the day-ahead solar production and local load forecasts that "
            "decide when the batteries charge.\n\nAs an intern you will benchmark probabilistic models "
            "against the current gradient-boosted forecast, add weather-ensemble features, and ship the "
            "winner behind the existing API. You will present your results to the trading desk."
        ),
        requirements=["Master's student in data science, statistics or engineering", "Python and SQL", "Time-series modelling", "Six-month convention de stage from Feb–Mar 2027"],
        nice_to_have=["Probabilistic forecasting (quantiles)", "Energy markets", "Docker"],
        compensation="€1,400/month + lunch vouchers", fit_score=9.1,
        fit_rationale="Day-ahead forecasting in energy is the brief's first choice, and the Brightwater demand forecast is the same problem one domain over. Lyon and hybrid both match.",
        strengths=["Shipped a demand forecast with a measured error reduction", "Time-series and Bayesian coursework", "LightGBM is the team's current baseline"],
        risks=["No direct energy-market experience", "Probabilistic forecasting only from coursework"],
        keywords=["time series", "probabilistic forecasting", "LightGBM", "Python", "SQL", "energy"],
        tags={"forecast", "energy", "ml"},
        why=("its day-ahead forecasts decide when 140 MWh of batteries charge — the kind of model whose errors someone pays for", "ses prévisions à J+1 décident quand 140 MWh de batteries se chargent — le genre de modèle dont chaque erreur se paie"),
        proof=("At Brightwater Utilities I took a pumping-station demand forecast from 6.1% to 4.3% MAPE and walked the operations team through the days it still got wrong", "Chez Brightwater Utilities, j'ai fait passer la prévision de demande des stations de pompage de 6,1 % à 4,3 % de MAPE, et j'ai présenté à l'exploitation les jours où elle se trompait encore"),
    ),
    _job(
        key="nimbus", pool="app:nimbus", company="Nimbus Labs", title="Machine Learning Research Intern — LLM Evaluation",
        title_fr="Stage Recherche en Machine Learning — Évaluation de LLM",
        location="Paris, France", posted_days_ago=12, discovered_days_ago=10,
        url="https://careers.example.com/nimbus-labs/ml-research-intern-evaluation",
        summary="Design evaluation suites for retrieval-augmented language models in a 12-person research lab.",
        description=(
            "Nimbus Labs builds retrieval-augmented assistants for legal and technical documentation. "
            "The research team publishes on evaluation methodology.\n\nYou will build an evaluation "
            "harness for long-document question answering, study where automatic metrics disagree with "
            "human judgement, and co-author an internal report — possibly a workshop paper."
        ),
        requirements=["MSc student in ML or NLP", "PyTorch", "Experience with transformer models", "Six months from February 2027"],
        nice_to_have=["Publication or research project", "French and English"],
        compensation="€1,600/month", fit_score=8.7,
        fit_rationale="NLP research with a clear deliverable; the clinical de-identification project shows transformer fine-tuning. Paris hybrid matches.",
        strengths=["Transformer fine-tuning project with a reported F1", "Bilingual French/English", "Statistics background suits evaluation work"],
        risks=["No prior publication", "Evaluation of generative models is new territory"],
        keywords=["NLP", "evaluation", "PyTorch", "transformers", "retrieval"],
        tags={"nlp", "ml"},
        why=("its research on where automatic metrics disagree with people is exactly the question I keep running into", "ses travaux sur les cas où les métriques automatiques contredisent le jugement humain rejoignent exactement la question que je me pose"),
        proof=("In my de-identification project I fine-tuned a French token classifier to 0.94 F1 and spent most of the time on why the errors clustered where they did", "Dans mon projet de dé-identification, j'ai entraîné un classifieur de tokens en français jusqu'à 0,94 de F1, et passé l'essentiel du temps à comprendre pourquoi les erreurs se concentraient"),
    ),
    _job(
        key="orbe", pool="app:orbe", company="Orbe Santé", title="Stage NLP — Notes cliniques",
        title_fr="Stage NLP — Notes cliniques", language="fr",
        location="Paris, France", posted_days_ago=6, discovered_days_ago=4,
        url="https://careers.example.com/orbe-sante/stage-nlp-notes-cliniques",
        summary="Extraire des informations structurées de comptes rendus hospitaliers, sous contrainte RGPD.",
        description=(
            "Orbe Santé aide les hôpitaux à structurer leurs comptes rendus. L'équipe NLP (cinq personnes) "
            "développe des modèles d'extraction d'entités médicales en français.\n\nVous travaillerez sur "
            "la détection des traitements et posologies, l'évaluation sur données annotées, et la "
            "pseudonymisation en amont du pipeline."
        ),
        requirements=["Master en data science ou TAL", "Python, PyTorch", "Modèles de type transformer", "Stage de 6 mois à partir de février 2027"],
        nice_to_have=["Connaissance du RGPD", "Données de santé"],
        compensation="1 300 €/mois", fit_score=8.2,
        fit_rationale="French clinical NLP is a direct continuation of the de-identification project; health is one of the brief's two preferred domains.",
        strengths=["De-identification project on synthetic clinical notes", "Native French", "Transformer fine-tuning"],
        risks=["No real hospital data experience"],
        keywords=["TAL", "NLP", "santé", "PyTorch", "RGPD", "extraction d'entités"],
        tags={"nlp", "ml"},
        why=("structurer des comptes rendus hospitaliers sans exposer les patients est un problème que j'ai déjà abordé par l'autre bout", "structurer des comptes rendus hospitaliers sans exposer les patients est un problème que j'ai déjà abordé par l'autre bout"),
        proof=("I built a de-identification model for synthetic French clinical notes, reaching 0.94 F1", "J'ai développé un modèle de pseudonymisation de notes cliniques synthétiques en français, à 0,94 de F1"),
    ),
    _job(
        key="saffron", pool="app:saffron", company="Saffron Retail", title="Pricing Analytics Intern",
        title_fr="Stage Analyste Pricing",
        location="Paris, France", posted_days_ago=34, discovered_days_ago=31,
        url="https://careers.example.com/saffron-retail/pricing-analytics-intern",
        summary="Measure promotion elasticity across 300 stores and help redesign the weekly markdown rules.",
        description=(
            "Saffron Retail runs 300 grocery stores. The pricing team models how promotions move "
            "volumes.\n\nYou will estimate price elasticities by category, build a simulator for the "
            "weekly markdown rules, and present scenarios to category managers."
        ),
        requirements=["Statistics or data science student", "SQL and Python", "Econometrics or regression modelling"],
        compensation="€1,350/month", fit_score=7.3,
        fit_rationale="Solid modelling with a business audience; retail is outside the preferred domains but the role is hands-on.",
        strengths=["Regression and Bayesian coursework", "Experience presenting models to operations staff"],
        risks=["Retail pricing is a new domain", "Some reporting in the missions"],
        keywords=["pricing", "elasticity", "SQL", "Python", "A/B testing"],
        tags={"analytics", "ml"},
        why=("its markdown rules are a modelling problem with an answer you can see in the next week's sales", "ses règles de démarque sont un problème de modélisation dont on voit la réponse dans les ventes de la semaine suivante"),
        proof=("My Brightwater forecast was judged by an operations team every Monday, which taught me to explain a model by its mistakes", "Ma prévision chez Brightwater était jugée chaque lundi par l'exploitation, ce qui m'a appris à expliquer un modèle par ses erreurs"),
    ),
    _job(
        key="pixel", pool="app:pixel", company="Pixel Harbor", title="ML Platform Intern",
        title_fr="Stage ML Platform",
        location="Paris, France", posted_days_ago=58, discovered_days_ago=55,
        url="https://careers.example.com/pixel-harbor/ml-platform-intern",
        summary="Help a game studio's data team move model training from notebooks to scheduled pipelines.",
        description="Pixel Harbor's data team trains player-churn and matchmaking models. You will containerise training jobs, add evaluation gates and document the platform.",
        requirements=["Python", "Docker", "Some ML experience"],
        compensation="€1,500/month", fit_score=7.8,
        fit_rationale="Engineering-leaning ML role with a clear deliverable; less modelling than preferred but strong mentoring.",
        strengths=["Docker and Python", "Automated a weekly report end to end"],
        risks=["More engineering than modelling"],
        keywords=["MLOps", "Docker", "Python", "pipelines"],
        tags={"data_eng", "ml"},
        why=("moving models out of notebooks is the step most data teams skip and regret", "sortir les modèles des notebooks est l'étape que la plupart des équipes data repoussent et regrettent"),
        proof=("At Brightwater I turned a manual weekly report into a scheduled Python and SQL job that ran unattended for the rest of the summer", "Chez Brightwater, j'ai transformé un rapport hebdomadaire manuel en job Python et SQL planifié, qui a tourné sans intervention tout l'été"),
    ),
    _job(
        key="ardent", pool="app:ardent", company="Ardent Robotics", title="Computer Vision Intern",
        title_fr="Stage Vision par ordinateur",
        location="Grenoble, France", posted_days_ago=71, discovered_days_ago=68,
        url="https://careers.example.com/ardent-robotics/computer-vision-intern",
        summary="Train defect-detection models for a warehouse picking robot.",
        description="Ardent Robotics builds picking arms for warehouses. The perception team needs an intern to improve defect detection on packaging.",
        requirements=["Computer vision coursework", "PyTorch", "C++ a plus"],
        compensation="€1,450/month", fit_score=6.4,
        fit_rationale="Strong team but vision is the weakest part of the profile and Grenoble is outside the preferred cities.",
        strengths=["PyTorch", "Deep learning coursework"],
        risks=["No computer vision project", "Location outside Paris/Lyon"],
        keywords=["computer vision", "PyTorch", "object detection"],
        tags={"vision", "ml"},
        why=("a picking robot is a model that fails in public, which is a good reason to measure it carefully", "un robot de préhension est un modèle qui échoue en public, ce qui est une bonne raison de le mesurer avec soin"),
        proof=("My deep-learning coursework included a detection project on a small industrial dataset", "Mes cours d'apprentissage profond comprenaient un projet de détection sur un petit jeu de données industriel"),
    ),
    _job(
        key="granite", pool="app:granite", company="Granite Bank", title="Risk Analytics Intern",
        title_fr="Stage Analyse des risques",
        location="Paris, France", posted_days_ago=40, discovered_days_ago=38,
        url="https://careers.example.com/granite-bank/risk-analytics-intern",
        summary="Monitor credit-scoring models and write the quarterly drift report.",
        description="Granite Bank's model-risk team monitors 30 credit models. Mostly reporting, with some statistical testing.",
        requirements=["Statistics", "SAS or Python", "Banking interest"],
        compensation="€1,500/month", fit_score=5.2,
        fit_rationale="Mostly reporting — close to a deal-breaker in the brief.",
        strengths=["Statistics background"], risks=["Reporting-heavy role", "Finance is not a preferred domain"],
        keywords=["credit risk", "model monitoring", "SAS", "Python"],
        tags={"finance", "analytics"},
        why=("model monitoring is where statistics meets consequences", "le suivi des modèles est l'endroit où la statistique rencontre ses conséquences"),
        proof=("I wrote the drift checks for my Brightwater forecast myself", "J'ai écrit moi-même les contrôles de dérive de ma prévision chez Brightwater"),
    ),
    # --- the deck ------------------------------------------------------------
    _job(
        key="quanta", pool="deck", company="Quanta Rail", title="Stage Recherche Opérationnelle — Planification des rames",
        title_fr="Stage Recherche Opérationnelle — Planification des rames", language="fr",
        location="Paris, France", remote="onsite", posted_days_ago=3, discovered_days_ago=1,
        url="https://careers.example.com/quanta-rail/stage-recherche-operationnelle",
        summary="Optimiser l'affectation des rames aux sillons pour réduire les kilomètres à vide.",
        description="Quanta Rail conçoit des outils de planification pour opérateurs ferroviaires. Vous modéliserez l'affectation des rames en programmation linéaire en nombres entiers et comparerez des heuristiques.",
        requirements=["Recherche opérationnelle", "Python", "Solveurs MILP (OR-Tools, Gurobi)"],
        compensation="1 400 €/mois", fit_score=7.6,
        fit_rationale="The bike-share rebalancing project is the same family of problem; optimisation rather than ML, which the brief accepts.",
        strengths=["MILP project with OR-Tools", "Operations research coursework"], risks=["Onsite only", "Less ML than preferred"],
        keywords=["recherche opérationnelle", "MILP", "OR-Tools", "Python"],
        tags={"or", "logistics"},
        why=("affecter des rames à des sillons est un problème d'optimisation dont chaque kilomètre à vide se compte", "affecter des rames à des sillons est un problème d'optimisation dont chaque kilomètre à vide se compte"),
        proof=("I built a mixed-integer model for overnight bike-share rebalancing that cut simulated empty-station hours by 31%", "J'ai construit un modèle en nombres entiers pour le rééquilibrage nocturne de vélos en libre-service, qui a réduit de 31 % les heures de stations vides en simulation"),
    ),
    _job(
        key="lumen", pool="deck", company="Lumen Maps", title="Geospatial Machine Learning Intern",
        title_fr="Stage Machine Learning géospatial",
        location="Lyon, France", posted_days_ago=5, discovered_days_ago=2,
        url="https://careers.example.com/lumen-maps/geospatial-ml-intern",
        summary="Predict rooftop solar potential from aerial imagery and open cadastral data.",
        description="Lumen Maps sells solar-potential maps to municipalities. You will improve the rooftop segmentation model and calibrate the yield estimate against metered installations.",
        requirements=["Python", "Machine learning", "Interest in GIS"],
        nice_to_have=["GeoPandas", "PyTorch"], compensation="€1,350/month", fit_score=7.9,
        fit_rationale="Energy-adjacent, Lyon, hybrid; the spatial statistics course helps, but imagery is new.",
        strengths=["Spatial statistics coursework", "Energy interest", "Lyon"], risks=["No imagery or segmentation project"],
        keywords=["geospatial", "segmentation", "solar", "GeoPandas", "PyTorch"],
        tags={"geo", "energy", "ml"},
        why=("a solar-potential map is only as useful as its calibration against real meters", "une carte de potentiel solaire ne vaut que par son calage sur de vrais compteurs"),
        proof=("Calibrating a forecast against metered data is what my Brightwater internship was about", "Caler une prévision sur des données de compteurs, c'est précisément ce que j'ai fait chez Brightwater"),
    ),
    _job(
        key="atelier", pool="deck", company="Atelier Metric", title="Product Data Analyst Intern",
        title_fr="Stage Product Data Analyst",
        location="Paris, France", remote="remote", posted_days_ago=9, discovered_days_ago=7,
        url="https://careers.example.com/atelier-metric/product-data-analyst-intern",
        summary="Own the experimentation reporting for a B2B analytics product.",
        description="Atelier Metric's product team runs ~20 A/B tests a quarter. You will automate the analysis, define guardrail metrics and present results weekly.",
        requirements=["SQL", "Statistics (hypothesis testing)", "Python or R"],
        compensation="€1,300/month", fit_score=6.8,
        fit_rationale="Good statistics fit, fully remote, but closer to analytics than modelling.",
        strengths=["Statistics teaching", "SQL"], risks=["Analytics more than ML"],
        keywords=["A/B testing", "SQL", "experimentation", "product analytics"],
        tags={"analytics"},
        why=("twenty experiments a quarter is enough to make the analysis itself worth automating", "vingt expériences par trimestre suffisent pour que l'analyse elle-même mérite d'être automatisée"),
        proof=("I teach hypothesis testing to first-year students, which is a good way to find out which explanations survive", "J'enseigne les tests d'hypothèses en première année, ce qui est un bon moyen de savoir quelles explications tiennent"),
    ),
    _job(
        key="kestrel", pool="deck", company="Kestrel Capital", title="Quantitative Research Intern",
        title_fr="Stage Recherche quantitative",
        location="Paris, France", remote="onsite", posted_days_ago=14, discovered_days_ago=11,
        url="https://careers.example.com/kestrel-capital/quant-research-intern",
        summary="Research short-horizon volatility signals for a systematic fund.",
        description="Kestrel Capital is a 30-person systematic fund. Interns research one signal end to end, from data cleaning to a backtest reviewed by the investment committee.",
        requirements=["Strong probability and statistics", "Python", "Time series"],
        compensation="€2,500/month", fit_score=6.1,
        fit_rationale="Time-series skills transfer, but finance is outside the brief and the role is onsite.",
        strengths=["Time series and Bayesian statistics"], risks=["No finance experience", "Onsite only"],
        keywords=["quantitative research", "time series", "volatility", "backtesting"],
        tags={"finance", "forecast"},
        why=("a backtest reviewed by a committee is the strictest version of the validation I already care about", "un backtest relu par un comité est la version la plus exigeante de la validation qui me tient déjà à cœur"),
        proof=("My thesis is on uncertainty in short-term forecasts", "Mon mémoire porte sur l'incertitude des prévisions à court terme"),
    ),
    _job(
        key="brisa", pool="deck", company="Brisa Mobility", title="Stage Data Science — Prévision de la demande",
        title_fr="Stage Data Science — Prévision de la demande", language="fr",
        location="Bordeaux, France", posted_days_ago=11, discovered_days_ago=8,
        url="https://careers.example.com/brisa-mobility/stage-prevision-demande",
        summary="Prévoir la demande de vélos par station pour piloter le rééquilibrage.",
        description="Brisa Mobility exploite 4 000 vélos partagés. Vous construirez la prévision de demande par station et heure qui alimente l'optimisation des tournées de camions.",
        requirements=["Python", "Séries temporelles", "SQL"],
        compensation="1 350 €/mois", fit_score=7.2,
        fit_rationale="Exactly the bike-share problem from the project, plus forecasting — but Bordeaux is outside the preferred cities.",
        strengths=["Bike-share rebalancing project", "Forecasting experience"], risks=["Bordeaux"],
        keywords=["prévision", "séries temporelles", "mobilité", "Python"],
        tags={"forecast", "or"},
        why=("la prévision de demande par station est l'entrée qui manquait à mon projet de rééquilibrage", "la prévision de demande par station est l'entrée qui manquait à mon projet de rééquilibrage"),
        proof=("My bike-share rebalancing project took demand as given — this role builds the part I had to assume", "Mon projet de rééquilibrage prenait la demande comme une donnée — ce poste construit la partie que j'avais dû supposer"),
    ),
    _job(
        key="corvid", pool="deck", company="Corvid Security", title="Anomaly Detection Intern",
        title_fr="Stage Détection d'anomalies",
        location="Rennes, France", posted_days_ago=19, discovered_days_ago=16, deferred_days_ago=2,
        url="https://careers.example.com/corvid-security/anomaly-detection-intern",
        summary="Detect unusual login patterns across 2 million accounts with unsupervised models.",
        description="Corvid Security's detection team wants to replace static rules with learned baselines per customer.",
        requirements=["Machine learning", "Python", "Interest in security"],
        compensation="€1,400/month", fit_score=7.0,
        fit_rationale="Interesting unsupervised problem; Rennes and security are both outside the brief.",
        strengths=["Leak-suspicion report is anomaly detection in miniature"], risks=["Rennes", "No security background"],
        keywords=["anomaly detection", "unsupervised learning", "security", "Python"],
        tags={"ml"},
        why=("learned baselines per customer are a better answer than rules nobody remembers writing", "des références apprises par client valent mieux que des règles que plus personne ne se souvient d'avoir écrites"),
        proof=("The leak-suspicion report I automated at Brightwater was anomaly detection on pumping data", "Le rapport de suspicion de fuites que j'ai automatisé chez Brightwater était de la détection d'anomalies sur des données de pompage"),
    ),
    _job(
        key="verdant", pool="deck", company="Verdant Foods", title="Stage Data Science Supply Chain",
        title_fr="Stage Data Science Supply Chain", language="fr",
        location="Lille, France", remote="onsite", posted_days_ago=27, discovered_days_ago=24,
        url="https://careers.example.com/verdant-foods/stage-data-science-supply-chain",
        summary="Réduire le gaspillage en prévoyant les ventes de produits frais par magasin.",
        description="Verdant Foods distribue des produits frais à 600 magasins. Vous améliorerez la prévision des ventes et mesurerez son effet sur la casse.",
        requirements=["Python", "Prévision", "SQL"], compensation="1 300 €/mois", fit_score=6.5,
        fit_rationale="Forecasting fit, but Lille and onsite both cut against the brief.",
        strengths=["Demand forecasting experience"], risks=["Lille, onsite"],
        keywords=["supply chain", "prévision", "gaspillage", "SQL"],
        tags={"forecast", "logistics"},
        why=("chaque point de précision sur les produits frais se mesure directement en casse évitée", "chaque point de précision sur les produits frais se mesure directement en casse évitée"),
        proof=("I cut a demand forecast's error by a third at Brightwater", "J'ai réduit d'un tiers l'erreur d'une prévision de demande chez Brightwater"),
    ),
    # --- the discard pile ----------------------------------------------------
    _job(
        key="spindle", pool="discarded", company="Spindle Media", title="Marketing Data Intern",
        title_fr="Stage Data Marketing",
        location="Paris, France", posted_days_ago=20, discovered_days_ago=18,
        url="https://careers.example.com/spindle-media/marketing-data-intern",
        summary="Weekly campaign dashboards for a media group.",
        description="Build and maintain campaign dashboards.",
        requirements=["Excel", "Looker"], compensation="Statutory minimum", fit_score=3.9,
        fit_rationale="Pure reporting — a deal-breaker in the brief.", strengths=["Power BI"], risks=["Reporting only"],
        keywords=["dashboards", "marketing"], tags={"analytics"},
        why=("its audience data is broad", "ses données d'audience sont riches"), proof=("I have built Power BI reports", "J'ai construit des rapports Power BI"),
    ),
    _job(
        key="gilded", pool="discarded", company="Gilded Hotels", title="Business Intelligence Intern",
        title_fr="Stage Business Intelligence",
        location="Nice, France", remote="onsite", posted_days_ago=30, discovered_days_ago=29,
        url="https://careers.example.com/gilded-hotels/bi-intern",
        summary="Occupancy reporting for a hotel chain.", description="Maintain occupancy and revenue reports.",
        requirements=["SQL", "Power BI"], compensation="€900/month", fit_score=4.4,
        fit_rationale="Reporting role in Nice; outside the brief on both counts.", strengths=["SQL"], risks=["Reporting", "Location"],
        keywords=["BI", "Power BI"], tags={"analytics"},
        why=("its revenue data is rich", "ses données de revenus sont riches"), proof=("I know SQL", "Je maîtrise SQL"),
    ),
    # --- revealed by the canned Jobs-chat searches -----------------------------
    _job(
        key="boreal", pool="search:energy", company="Boréal Énergie", title="Climate Data Science Intern",
        title_fr="Stage Data Science Climat",
        location="Lyon, France", posted_days_ago=2, discovered_days_ago=0,
        url="https://careers.example.com/boreal-energie/climate-data-science-intern",
        summary="Downscale climate projections to forecast hydro output for 2030–2050.",
        description="Boréal Énergie runs 12 hydro plants. You will build a statistical downscaling of climate projections and estimate future inflows.",
        requirements=["Statistics", "Python", "Time series"], compensation="€1,400/month", fit_score=8.4,
        fit_rationale="Energy, Lyon, hybrid and statistical forecasting — every line of the brief.",
        strengths=["Time series", "Spatial statistics"], risks=["Climate models are new"],
        keywords=["climate", "hydro", "downscaling", "time series"], tags={"forecast", "energy", "geo"},
        why=("forecasting hydro inflows for 2050 is forecasting with the stakes made explicit", "prévoir les apports hydrauliques de 2050, c'est la prévision avec des enjeux rendus explicites"),
        proof=("My thesis on forecast uncertainty is the half of this problem I already work on", "Mon mémoire sur l'incertitude des prévisions est la moitié de ce problème sur laquelle je travaille déjà"),
    ),
    _job(
        key="solstice", pool="search:energy", company="Solstice Power", title="Grid Optimisation Intern",
        title_fr="Stage Optimisation du réseau",
        location="Lyon, France", posted_days_ago=4, discovered_days_ago=0,
        url="https://careers.example.com/solstice-power/grid-optimisation-intern",
        summary="Schedule EV-charging loads to flatten evening peaks on a distribution grid.",
        description="Solstice Power's flexibility team optimises charging schedules for 8,000 connected chargers.",
        requirements=["Optimisation", "Python"], compensation="€1,350/month", fit_score=7.7,
        fit_rationale="Optimisation in energy, in Lyon; less ML than the brief's first choice.",
        strengths=["MILP project", "Forecasting"], risks=["Optimisation-heavy"],
        keywords=["optimisation", "EV charging", "energy", "Python"], tags={"or", "energy"},
        why=("flattening an evening peak is an optimisation problem with a forecast inside it", "lisser une pointe du soir, c'est un problème d'optimisation avec une prévision à l'intérieur"),
        proof=("My bike-share project scheduled trucks overnight with a MILP", "Mon projet de vélos partagés planifiait les camions de nuit avec un MILP"),
    ),
    _job(
        key="cerulean", pool="search:energy", company="Cerulean Water", title="Hydrology ML Intern",
        title_fr="Stage Machine Learning hydrologique",
        location="Grenoble, France", posted_days_ago=8, discovered_days_ago=0,
        url="https://careers.example.com/cerulean-water/hydrology-ml-intern",
        summary="Nowcast river levels from rain-gauge networks for flood warnings.",
        description="Cerulean Water operates flood-warning services. You will compare ML nowcasting models against the current hydrological model.",
        requirements=["Python", "ML", "Time series"], compensation="€1,300/month", fit_score=7.4,
        fit_rationale="Water and forecasting match the Brightwater experience; Grenoble is outside the preferred cities.",
        strengths=["Water-utility experience", "Forecasting"], risks=["Grenoble"],
        keywords=["hydrology", "nowcasting", "time series", "Python"], tags={"forecast", "ml"},
        why=("a flood warning is a forecast that someone acts on within the hour", "une alerte crue est une prévision sur laquelle quelqu'un agit dans l'heure"),
        proof=("I already forecast water demand for a utility", "J'ai déjà prévu la demande en eau pour un distributeur"),
    ),
    _job(
        key="lexica", pool="search:nlp", company="Lexica", title="NLP Engineer Intern",
        title_fr="Stage Ingénieur NLP", remote="remote",
        location="Remote, France", posted_days_ago=3, discovered_days_ago=0,
        url="https://careers.example.com/lexica/nlp-engineer-intern",
        summary="Build multilingual search for a legal-tech startup, fully remote.",
        description="Lexica indexes French and EU case law. You will evaluate embedding models for bilingual retrieval and ship the best one.",
        requirements=["NLP", "Python", "Embeddings / retrieval"], compensation="€1,500/month", fit_score=8.0,
        fit_rationale="NLP, remote, bilingual — strong match; retrieval is new but adjacent.",
        strengths=["Transformers", "Bilingual"], risks=["Retrieval systems are new"],
        keywords=["NLP", "retrieval", "embeddings", "multilingual"], tags={"nlp", "ml"},
        why=("bilingual legal search is the place where an embedding's language bias becomes visible", "la recherche juridique bilingue est l'endroit où le biais linguistique d'un embedding devient visible"),
        proof=("I fine-tuned a French transformer for de-identification", "J'ai entraîné un transformer français pour la pseudonymisation"),
    ),
    _job(
        key="parole", pool="search:nlp", company="Parole Health", title="Speech & NLP Intern",
        title_fr="Stage Speech & NLP", remote="remote",
        location="Remote, France", posted_days_ago=6, discovered_days_ago=0,
        url="https://careers.example.com/parole-health/speech-nlp-intern",
        summary="Summarise doctor–patient consultations from transcripts, with privacy built in.",
        description="Parole Health transcribes consultations for GPs. You will evaluate summarisation quality and redaction.",
        requirements=["NLP", "PyTorch"], compensation="€1,400/month", fit_score=7.8,
        fit_rationale="Health NLP with redaction — close to the de-identification project; remote.",
        strengths=["De-identification", "French"], risks=["Speech is new"],
        keywords=["NLP", "summarisation", "health", "privacy"], tags={"nlp"},
        why=("summarising a consultation without leaking it is two problems I care about at once", "résumer une consultation sans la divulguer, ce sont deux problèmes qui m'intéressent à la fois"),
        proof=("My de-identification model reached 0.94 F1 on synthetic notes", "Mon modèle de pseudonymisation atteint 0,94 de F1 sur des notes synthétiques"),
    ),
    _job(
        key="fathom", pool="search:default", company="Fathom Analytics", title="Data Scientist Intern",
        title_fr="Stage Data Scientist",
        location="Paris, France", posted_days_ago=1, discovered_days_ago=0,
        url="https://careers.example.com/fathom-analytics/data-scientist-intern",
        summary="Churn and lifetime-value models for subscription businesses.",
        description="Fathom Analytics builds churn models for subscription clients. You will own one client's model end to end.",
        requirements=["Python", "ML", "SQL"], compensation="€1,400/month", fit_score=7.5,
        fit_rationale="Hands-on modelling in Paris; domain neutral.", strengths=["Python, SQL, LightGBM"], risks=["Consulting pace"],
        keywords=["churn", "machine learning", "SQL"], tags={"ml", "analytics"},
        why=("owning one client's model end to end is the best way to learn what end to end means", "porter le modèle d'un client de bout en bout est la meilleure façon d'apprendre ce que cela veut dire"),
        proof=("My Brightwater forecast went from data extract to a report the operations team used weekly", "Ma prévision chez Brightwater est passée de l'extraction des données à un rapport utilisé chaque semaine"),
    ),
    _job(
        key="mosaic", pool="search:default", company="Mosaic Insurance", title="Actuarial Data Science Intern",
        title_fr="Stage Data Science actuarielle",
        location="Paris, France", posted_days_ago=4, discovered_days_ago=0,
        url="https://careers.example.com/mosaic-insurance/actuarial-data-science-intern",
        summary="Gradient-boosted claim-frequency models for home insurance.",
        description="Compare GLMs and gradient boosting for claim frequency, with interpretability constraints.",
        requirements=["Statistics", "Python or R"], compensation="€1,450/month", fit_score=6.9,
        fit_rationale="Solid statistics role; insurance is not a preferred domain.", strengths=["LightGBM", "R"], risks=["Domain"],
        keywords=["GLM", "gradient boosting", "insurance"], tags={"ml", "finance"},
        why=("interpretability constraints make model choice a real decision", "les contraintes d'interprétabilité font du choix de modèle une vraie décision"),
        proof=("I explained a gradient-boosted forecast to non-specialists every week", "J'ai expliqué chaque semaine une prévision par gradient boosting à des non-spécialistes"),
    ),
    _job(
        key="halcyon", pool="search:default", company="Halcyon Labs", title="Applied ML Intern",
        title_fr="Stage Machine Learning appliqué",
        location="Lyon, France", posted_days_ago=2, discovered_days_ago=0,
        url="https://careers.example.com/halcyon-labs/applied-ml-intern",
        summary="Forecast lab-equipment failures from sensor logs.",
        description="Predictive maintenance for laboratory equipment from sensor time series.",
        requirements=["Python", "Time series", "ML"], compensation="€1,350/month", fit_score=8.0,
        fit_rationale="Time-series ML in Lyon, hybrid.", strengths=["Forecasting"], risks=["Sensor data is new"],
        keywords=["predictive maintenance", "time series", "Python"], tags={"forecast", "ml"},
        why=("predictive maintenance is forecasting where the cost of a miss is known", "la maintenance prédictive, c'est de la prévision dont le coût d'une erreur est connu"),
        proof=("I forecast pump demand from station logs at Brightwater", "J'ai prévu la demande des pompes à partir de leurs journaux chez Brightwater"),
    ),
    # --- revealed by the canned pastes ----------------------------------------
    _job(
        key="papyrus", pool="link", company="Papyrus AI", title="Document AI Intern",
        title_fr="Stage Document AI", source="manual",
        location="Paris, France", posted_days_ago=5, discovered_days_ago=0,
        url="https://careers.example.com/papyrus-ai/document-ai-intern",
        summary="Extract tables and fields from scanned invoices with layout-aware models.",
        description="Papyrus AI automates accounts-payable. You will benchmark layout-aware transformers on scanned invoices and improve the field-extraction F1.",
        requirements=["NLP or computer vision", "PyTorch"], compensation="€1,500/month", fit_score=7.9,
        fit_rationale="Token classification on documents — the de-identification project is a close cousin; Paris hybrid.",
        strengths=["Token classification project", "PyTorch"], risks=["Layout models are new"],
        keywords=["document AI", "NLP", "PyTorch", "information extraction"], tags={"nlp", "ml"},
        why=("field extraction is token classification with a layout attached", "l'extraction de champs, c'est de la classification de tokens avec une mise en page en plus"),
        proof=("My de-identification model was token classification on French text", "Mon modèle de pseudonymisation faisait de la classification de tokens sur du texte français"),
    ),
    _job(
        key="tidewater", pool="text", company="Tidewater Logistics", title="Data Engineering Intern",
        title_fr="Stage Data Engineering", source="manual", url_status="unchecked", url_http_status=0,
        location="Le Havre, France", posted_days_ago=0, discovered_days_ago=0, url="",
        summary="Build the port-call data pipeline that feeds berth-planning models.",
        description="Tidewater Logistics plans berths for container ships. You will build the ingestion pipeline for vessel positions and port calls.",
        requirements=["Python", "SQL", "Data pipelines"], compensation="€1,300/month", fit_score=6.6,
        fit_rationale="Engineering more than modelling, in Le Havre; useful but outside the brief.",
        strengths=["Python, SQL, Docker"], risks=["Location", "Engineering-focused"],
        keywords=["data engineering", "pipelines", "SQL", "logistics"], tags={"data_eng", "logistics"},
        why=("berth planning is only as good as the data arriving on time", "la planification des quais ne vaut que par des données qui arrivent à l'heure"),
        proof=("I scheduled a weekly Python and SQL pipeline at Brightwater", "J'ai planifié un pipeline Python et SQL hebdomadaire chez Brightwater"),
    ),
]

# What the canned Jobs-chat prompts say, and which pool each reveals. The first
# focus on the empty box fills prompt 0, the next prompt 1, and so on.
SEARCHES = [
    {
        "key": "energy",
        "prompt": "Energy and climate teams in Lyon, hybrid",
        "notes": (
            "Weighted energy and climate employers in Lyon first, as asked. Boréal Énergie "
            "is the strongest match on every line of the brief; Cerulean Water is in Grenoble, "
            "so it ranks lower despite the forecasting fit."
        ),
    },
    {
        "key": "nlp",
        "prompt": "Remote-friendly NLP internships",
        "notes": (
            "Two fully remote NLP roles. Both reward the de-identification project; Lexica's "
            "retrieval work is the newer skill, Parole Health's privacy angle the closer one."
        ),
    },
    {
        "key": "default",
        "prompt": "",
        "notes": "Searched with the brief as written. Halcyon Labs (Lyon, time series) is the standout.",
    },
]

LINK_IMPORT = "https://careers.example.com/papyrus-ai/document-ai-intern"
TEXT_IMPORT = (
    "Tidewater Logistics — Data Engineering Intern (Le Havre)\n\n"
    "We plan berths for 1,200 container-ship calls a year. Join the data team for six months from "
    "February 2027 to build the ingestion pipeline for vessel positions and port calls that feeds our "
    "berth-planning models. Python, SQL, and an interest in logistics. €1,300/month."
)

PERSONALISATION = {
    "en": "I met their head of forecasting at the ESD careers fair in September — she suggested I mention the Brightwater error analysis.",
    "fr": "J'ai rencontré leur responsable data au forum ESD en septembre — elle m'a conseillé de mentionner l'analyse d'erreurs chez Brightwater.",
}

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
#
# `events` are (days ago, from, to, note). `documents` are the languages a run
# has already written the résumé and letter in.

APPLICATIONS = {
    "helio": {
        "status": "technical_test", "pinned": True, "language": "en", "documents": ["en"],
        "interview_prep": True, "contacts": True,
        "notes": "Take-home: probabilistic forecast for one substation, due Friday. Ask about the trading desk's error tolerance.",
        "next_action": "Submit the take-home", "next_action_days_ahead": 3,
        "applied_days_ago": 19,
        "events": [
            (21, "", "saved", "Swiped right."),
            (20, "saved", "preparing", "Generated the résumé and the cover letter."),
            (19, "preparing", "applied", "Applied through the careers page."),
            (11, "applied", "hr_pre_call", "Recruiter call booked for Tuesday."),
            (8, "hr_pre_call", "hr_interview", "Good call — moving to the team interview."),
            (2, "hr_interview", "technical_test", "Take-home sent by the forecasting lead."),
        ],
    },
    "saffron": {
        "status": "applied", "pinned": False, "language": "en", "documents": ["en"],
        "follow_up": True, "applied_days_ago": 18,
        "notes": "", "next_action": "", "events": [
            (30, "", "saved", "Swiped right."),
            (19, "saved", "preparing", "Generated the documents."),
            (18, "preparing", "applied", "Applied through the careers page."),
        ],
    },
    "nimbus": {
        "status": "preparing", "pinned": False, "language": "en", "documents": ["en"],
        "notes": "Read their evaluation blog post before writing the letter.", "next_action": "Apply before the end of the week",
        "next_action_days_ahead": 4, "events": [
            (9, "", "saved", "Swiped up — a favourite."),
            (1, "saved", "preparing", "Generated the résumé and the cover letter."),
        ],
    },
    "orbe": {
        "status": "saved", "pinned": True, "language": "fr", "documents": [],
        "notes": "", "next_action": "", "events": [(3, "", "saved", "Swiped up — a favourite.")],
    },
    "pixel": {
        "status": "offer", "pinned": False, "language": "en", "documents": ["en"], "applied_days_ago": 50,
        "notes": "Offer: €1,500/month, start 3 February. Answer by the 20th.", "next_action": "Decide on the offer",
        "next_action_days_ahead": 9, "events": [
            (54, "", "saved", "Swiped right."),
            (50, "saved", "applied", "Applied."),
            (40, "applied", "hr_pre_call", ""),
            (33, "hr_pre_call", "manager_interview", "Interview with the data lead."),
            (5, "manager_interview", "offer", "Offer received by e-mail."),
        ],
    },
    "ardent": {
        "status": "rejected", "pinned": False, "language": "en", "documents": ["en"], "applied_days_ago": 64,
        "notes": "Rejected after the CV screen — they wanted a vision project.", "next_action": "",
        "events": [
            (66, "", "saved", "Swiped right."),
            (64, "saved", "applied", "Applied."),
            (45, "applied", "rejected", "Generic rejection e-mail; no vision project on the CV."),
        ],
    },
    "granite": {
        "status": "saved", "pinned": False, "language": "en", "documents": [], "trashed_days_ago": 12,
        "notes": "", "next_action": "", "events": [(37, "", "saved", "Swiped right.")],
    },
}

# Fictional people for the contact shortlists, by role.
PEOPLE = [
    ("Camille Lefèvre", "Head of Data Science", "hiring_manager"),
    ("Hugo Bernard", "Senior Data Scientist", "team_member"),
    ("Léa Robert", "Talent Acquisition Partner", "recruiter"),
    ("Nadia Haddad", "ML Engineer (alumna, ESD 2023)", "alumni"),
]
