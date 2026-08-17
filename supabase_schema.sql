-- À exécuter dans Supabase > SQL Editor
-- Équivalent des migrations Doctrine du projet Symfony

create table if not exists postes (
    id bigint generated always as identity primary key,
    type_poste varchar(30)
);

create table if not exists carterfid (
    id bigint generated always as identity primary key,
    uidcarte varchar(30) unique,
    couleur varchar(15),
    isentree boolean default false
);

create table if not exists employes (
    id bigint generated always as identity primary key,
    nom varchar(20),
    prenom varchar(20),
    matricule varchar(15) not null unique,
    date_embauche date,
    status varchar(13) default 'Actif',
    user_id uuid references auth.users(id) on delete set null,
    id_poste bigint not null references postes(id),
    -- NULLABLE : un employé promu depuis un candidat n'a pas encore de carte
    -- au moment de sa création ; elle est assignée plus tard.
    carterfid_id bigint unique references carterfid(id)
);

create table if not exists presences (
    id bigint generated always as identity primary key,
    datedujour date not null,
    statut varchar(50),
    dureetravail integer,
    id_employe bigint not null references employes(id) on delete cascade
);

create table if not exists presence_entree (
    id bigint generated always as identity primary key,
    date date not null,
    heure_entree time not null,
    ack boolean default false,
    id_employe bigint references employes(id) on delete cascade
);

create table if not exists sorties (
    id bigint generated always as identity primary key,
    date date not null,
    heure_sortie time not null,
    id_employe bigint not null references employes(id) on delete cascade
);

create table if not exists absences (
    id bigint generated always as identity primary key,
    dateabsence date not null,
    raison varchar(255),
    idemploye bigint not null references employes(id) on delete cascade
);

-- Index utiles pour les requêtes du quotidien (dashboard, pointage)
create index if not exists idx_presences_employe_jour on presences(id_employe, datedujour);
create index if not exists idx_entree_employe_jour on presence_entree(id_employe, date);
create index if not exists idx_sortie_employe_jour on sorties(id_employe, date);

create table if not exists candidats (
    id bigint generated always as identity primary key,
    nom varchar(50) not null,
    heure_inscription timestamptz not null default now(),
    statut varchar(12) not null default 'attente', -- attente / actif / historique
    poste_attribue varchar(30),
    heure_acceptation timestamptz,
    heure_retrait timestamptz,
    ip_inscription varchar(45),
    -- Lien vers le compte Supabase Auth créé au register (fusion register / candidat)
    user_id uuid references auth.users(id) on delete set null,
    -- Lien vers l'employé créé lors de l'acceptation. Reste renseigné même
    -- après passage du candidat en "historique" (l'employé, lui, ne bouge pas).
    employe_id bigint references employes(id) on delete set null
);

-- Un seul candidat "actif" possible à la fois, garanti par la BDD
create unique index if not exists uniq_candidat_actif
    on candidats ((statut = 'actif'))
    where statut = 'actif';

create table if not exists face_encodings (
    id bigint generated always as identity primary key,
    employe_id bigint not null unique references employes(id) on delete cascade,
    encoding jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz
);
 
create index if not exists idx_face_encodings_employe on face_encodings(employe_id);
 
-- Pas de RLS ici, comme le reste du schéma : toutes les requêtes passent
-- par FastAPI avec la clé service_role côté serveur.
 

alter table postes add column if not exists poids integer not null default 1;
-- Rôle admin/user stocké dans les métadonnées Supabase Auth (user_metadata.role),
-- lisible directement dans le JWT décodé côté FastAPI (voir app/core/security.py).
-- Pas de RLS ici car toutes les requêtes passent par FastAPI (clé service_role côté serveur),
-- pas par le client Supabase directement. Si un jour le frontend interroge Supabase en direct
-- (PostgREST), active RLS sur chaque table et écris des policies basées sur auth.uid().

-- ---------------------------------------------------------------------------
-- MIGRATION : à exécuter si la base existe déjà (candidats -> employé,
-- register fusionné, carte RFID assignée après coup). Ces instructions sont
-- idempotentes, tu peux les relancer sans risque.
-- ---------------------------------------------------------------------------

alter table employes alter column carterfid_id drop not null;
alter table employes alter column id_poste drop not null;

alter table candidats add column if not exists user_id uuid references auth.users(id) on delete set null;
alter table candidats add column if not exists employe_id bigint references employes(id) on delete set null;

