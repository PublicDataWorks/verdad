#!/usr/bin/env python3
"""Generate a baseline schema migration from the live Supabase project.

Read-only: every statement this script sends is a SELECT against the catalog,
issued through the Supabase Management API (`POST /v1/projects/<ref>/database/query`).
Authentication is supplied by the environment (the agent proxy or an
`Authorization: Bearer $SUPABASE_ACCESS_TOKEN` header); no secret is read,
printed or stored by this script.

Usage:
    python scripts/dump_schema_baseline.py -o supabase/migrations/<ts>_baseline_public_schema.sql

Environment:
    SUPABASE_PROJECT_REF        project ref (default: dzujjhzgzguciwryzwlx)
    SUPABASE_MANAGEMENT_API_URL API base (default: https://api.supabase.com)
    SUPABASE_BASELINE_SCHEMAS   comma-separated schemas (default: public,profiles)
    SUPABASE_ACCESS_TOKEN       optional; sent as a bearer token when set

Emission order is dependency-safe: schemas, extensions, enums, sequences,
tables (columns), primary/unique/check constraints, foreign keys, views and
materialized views, functions (trigger functions first), triggers, indexes not
backed by a constraint, RLS flags, policies, grants, comments. The two
`cron.schedule` jobs that exist in production are printed as a trailing comment
block; they are deliberately not executed by this file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from collections import OrderedDict, defaultdict

DEFAULT_REF = "dzujjhzgzguciwryzwlx"
DEFAULT_API = "https://api.supabase.com"
DEFAULT_SCHEMAS = "public,profiles"
GRANTEES = ("anon", "authenticated", "service_role")

# Extensions Supabase installs/manages for a project (or that cannot be created
# from a migration): emitted as comments so the baseline stays runnable.
PLATFORM_EXTENSIONS = {
    "plpgsql",
    "pg_cron",
    "pg_net",
    "pg_stat_statements",
    "pg_tle",
    "pgsodium",
    "supabase_vault",
    "supabase-dbdev",
}

RESERVED = {
    "all", "analyse", "analyze", "and", "any", "array", "as", "asc", "authorization", "between",
    "both", "case", "cast", "check", "collate", "column", "constraint", "create", "cross",
    "current_date", "current_role", "current_time", "current_timestamp", "current_user", "default",
    "deferrable", "desc", "distinct", "do", "else", "end", "except", "false", "for", "foreign",
    "from", "full", "grant", "group", "having", "in", "initially", "inner", "intersect", "into",
    "is", "isnull", "join", "leading", "left", "like", "limit", "localtime", "localtimestamp",
    "natural", "new", "not", "notnull", "null", "offset", "old", "on", "only", "or", "order",
    "outer", "overlaps", "placing", "primary", "references", "right", "select", "session_user",
    "similar", "some", "table", "then", "to", "trailing", "true", "union", "unique", "user",
    "using", "verbose", "when", "where", "window", "with",
}


class Client:
    def __init__(self, ref: str, api: str) -> None:
        self.url = f"{api.rstrip('/')}/v1/projects/{ref}/database/query"
        self.token = os.environ.get("SUPABASE_ACCESS_TOKEN")
        self.queries = 0

    def query(self, sql: str):
        # An empty search_path makes format_type / pg_get_*def emit fully
        # schema-qualified names, the way pg_dump does.
        sql = "set local search_path = '';\n" + sql
        body = json.dumps({"query": sql}).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            payload = resp.read().decode()
        self.queries += 1
        data = json.loads(payload)
        if isinstance(data, dict):
            raise SystemExit(f"query failed: {data}\nSQL: {sql[:400]}")
        return data


def ident(name: str) -> str:
    if re.fullmatch(r"[a-z_][a-z0-9_]*", name or "") and name not in RESERVED:
        return name
    return '"' + (name or "").replace('"', '""') + '"'


def qname(schema: str, name: str) -> str:
    return f"{ident(schema)}.{ident(name)}"


def lit(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def in_list(values) -> str:
    return ", ".join(lit(v) for v in values)


class Dumper:
    def __init__(self, client: Client, schemas) -> None:
        self.c = client
        self.schemas = list(schemas)
        self.s_in = in_list(self.schemas)
        self.out = []

    # -- output helpers -------------------------------------------------
    def banner(self, title: str) -> None:
        self.out.append("")
        self.out.append("-- " + "-" * 74)
        self.out.append(f"-- {title}")
        self.out.append("-- " + "-" * 74)
        self.out.append("")

    def emit(self, text: str) -> None:
        text = text.rstrip()
        if not text.endswith(";"):
            text += ";"
        self.out.append(text)

    def note(self, text: str) -> None:
        self.out.append(f"-- {text}" if text else "--")

    # -- sections -------------------------------------------------------
    def header(self, counts_placeholder: str) -> None:
        self.out.append("-- Baseline schema for the VERDAD Supabase project.")
        self.out.append("--")
        self.out.append("-- Generated by scripts/dump_schema_baseline.py from the live database")
        self.out.append(f"-- (schemas: {', '.join(self.schemas)}). It is a snapshot of what production")
        self.out.append("-- actually runs, not a replay of the repo's history: 24 of the 29 versions in")
        self.out.append("-- supabase_migrations.schema_migrations were applied out-of-band and their SQL")
        self.out.append("-- never landed in git (the placeholder files next to this one stand in for")
        self.out.append("-- them), and the files in supabase/database/sql/ are historical.")
        self.out.append("--")
        self.out.append("-- This file is NOT meant to be run against production. Production already has")
        self.out.append("-- every object below; mark it applied instead:")
        self.out.append("--     supabase migration repair --linked --status applied 20260915000000")
        self.out.append("-- See docs/OPERATIONS.md, 'Database schema and migrations'.")
        self.out.append("--")
        self.out.append(counts_placeholder)
        self.out.append("")
        self.emit("SET check_function_bodies = false")

    def schemas_section(self) -> None:
        self.banner("Schemas")
        for s in self.schemas:
            if s == "public":
                continue
            self.emit(f"CREATE SCHEMA IF NOT EXISTS {ident(s)}")

    def extensions(self) -> int:
        rows = self.c.query(
            "select e.extname, n.nspname, e.extversion "
            "from pg_extension e join pg_namespace n on n.oid = e.extnamespace "
            "order by e.extname"
        )
        self.banner("Extensions")
        host_schemas = sorted(
            {r["nspname"] for r in rows
             if r["extname"] not in PLATFORM_EXTENSIONS
             and r["nspname"] not in self.schemas and r["nspname"] != "pg_catalog"}
        )
        for s in host_schemas:
            self.emit(f"CREATE SCHEMA IF NOT EXISTS {ident(s)}")
        active = 0
        for r in rows:
            if r["extname"] in PLATFORM_EXTENSIONS:
                continue
            self.out.append(
                f'CREATE EXTENSION IF NOT EXISTS "{r["extname"]}" WITH SCHEMA '
                f"{ident(r['nspname'])};  -- version {r['extversion']}"
            )
            active += 1
        self.out.append("")
        self.note("Installed on the project but managed by the Supabase platform (or not")
        self.note("creatable from a migration); listed for the record only:")
        for r in rows:
            if r["extname"] in PLATFORM_EXTENSIONS:
                self.note(f'  CREATE EXTENSION IF NOT EXISTS "{r["extname"]}" WITH SCHEMA '
                          f'{ident(r["nspname"])};  -- version {r["extversion"]}')
        return active

    def enums(self) -> int:
        rows = self.c.query(
            "select n.nspname, t.typname, "
            "string_agg(quote_literal(e.enumlabel), ', ' order by e.enumsortorder) as labels "
            "from pg_type t "
            "join pg_namespace n on n.oid = t.typnamespace "
            "join pg_enum e on e.enumtypid = t.oid "
            f"where n.nspname in ({self.s_in}) "
            "and not exists (select 1 from pg_depend d where d.objid = t.oid "
            "  and d.classid = 'pg_type'::regclass and d.deptype = 'e') "
            "group by 1, 2 order by 1, 2"
        )
        other = self.c.query(
            "select n.nspname, t.typname, t.typtype from pg_type t "
            "join pg_namespace n on n.oid = t.typnamespace "
            f"where n.nspname in ({self.s_in}) and t.typtype in ('d', 'r') "
            "and not exists (select 1 from pg_depend d where d.objid = t.oid "
            "  and d.classid = 'pg_type'::regclass and d.deptype = 'e') "
            "order by 1, 2"
        )
        self.banner("Types (enums)")
        for r in rows:
            self.emit(f"CREATE TYPE {qname(r['nspname'], r['typname'])} AS ENUM ({r['labels']})")
        for r in other:
            self.note(f"WARNING: unhandled {r['typtype']} type {r['nspname']}.{r['typname']} "
                      "(domains/ranges are not emitted by the generator)")
        return len(rows)

    def sequences(self) -> int:
        rows = self.c.query(
            "select n.nspname, c.relname, format_type(s.seqtypid, null) as seqtype, "
            "s.seqstart, s.seqincrement, s.seqmin, s.seqmax, s.seqcache, s.seqcycle, "
            "d.deptype, dn.nspname as owner_schema, dc.relname as owner_table, a.attname as owner_col "
            "from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "join pg_sequence s on s.seqrelid = c.oid "
            "left join pg_depend d on d.classid = 'pg_class'::regclass and d.objid = c.oid "
            "  and d.deptype in ('a', 'i') "
            "left join pg_class dc on dc.oid = d.refobjid "
            "left join pg_namespace dn on dn.oid = dc.relnamespace "
            "left join pg_attribute a on a.attrelid = d.refobjid and a.attnum = d.refobjsubid "
            f"where c.relkind = 'S' and n.nspname in ({self.s_in}) "
            "order by 1, 2"
        )
        self.banner("Sequences")
        emitted = 0
        self.owned_sequences = []
        for r in rows:
            if r["deptype"] == "i":
                self.note(f"{r['nspname']}.{r['relname']} is the identity sequence of "
                          f"{r['owner_table']}.{r['owner_col']} (created with the table)")
                continue
            parts = [f"CREATE SEQUENCE IF NOT EXISTS {qname(r['nspname'], r['relname'])}"]
            parts.append(f"    AS {r['seqtype']}")
            parts.append(f"    START WITH {r['seqstart']}")
            parts.append(f"    INCREMENT BY {r['seqincrement']}")
            parts.append(f"    MINVALUE {r['seqmin']}")
            parts.append(f"    MAXVALUE {r['seqmax']}")
            parts.append(f"    CACHE {r['seqcache']}")
            if r["seqcycle"]:
                parts.append("    CYCLE")
            self.emit("\n".join(parts))
            emitted += 1
            if r["deptype"] == "a" and r["owner_table"]:
                self.owned_sequences.append(r)
        if not emitted:
            self.note("(no standalone sequences)")
        return emitted

    def tables(self):
        rels = self.c.query(
            "select n.nspname, c.relname, c.relkind, c.relpersistence "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            f"where n.nspname in ({self.s_in}) and c.relkind in ('r', 'p') "
            "and not exists (select 1 from pg_depend d where d.objid = c.oid "
            "  and d.classid = 'pg_class'::regclass and d.deptype = 'e') "
            "order by 1, 2"
        )
        cols = self.c.query(
            "select n.nspname, c.relname, a.attname, a.attnum, "
            "format_type(a.atttypid, a.atttypmod) as coltype, a.attnotnull, "
            "pg_get_expr(ad.adbin, ad.adrelid) as coldefault, a.attidentity, a.attgenerated, "
            "coll.collname "
            "from pg_attribute a "
            "join pg_class c on c.oid = a.attrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "left join pg_attrdef ad on ad.adrelid = a.attrelid and ad.adnum = a.attnum "
            "left join pg_collation coll on coll.oid = a.attcollation and coll.collname <> 'default' "
            f"where n.nspname in ({self.s_in}) and c.relkind in ('r', 'p') "
            "and a.attnum > 0 and not a.attisdropped "
            "order by n.nspname, c.relname, a.attnum"
        )
        by_table = defaultdict(list)
        for r in cols:
            by_table[(r["nspname"], r["relname"])].append(r)

        self.banner("Tables")
        count = 0
        for rel in rels:
            key = (rel["nspname"], rel["relname"])
            lines = []
            for cdef in by_table[key]:
                piece = f"    {ident(cdef['attname'])} {cdef['coltype']}"
                if cdef["collname"]:
                    piece += f" COLLATE {ident(cdef['collname'])}"
                if cdef["attgenerated"] == "s" and cdef["coldefault"]:
                    piece += f" GENERATED ALWAYS AS ({cdef['coldefault']}) STORED"
                elif cdef["attidentity"] in ("a", "d"):
                    kind = "ALWAYS" if cdef["attidentity"] == "a" else "BY DEFAULT"
                    piece += f" GENERATED {kind} AS IDENTITY"
                elif cdef["coldefault"] is not None:
                    piece += f" DEFAULT {cdef['coldefault']}"
                if cdef["attnotnull"]:
                    piece += " NOT NULL"
                lines.append(piece)
            self.emit(
                f"CREATE TABLE IF NOT EXISTS {qname(*key)} (\n" + ",\n".join(lines) + "\n)"
            )
            self.out.append("")
            count += 1
        for r in getattr(self, "owned_sequences", []):
            self.emit(
                f"ALTER SEQUENCE {qname(r['nspname'], r['relname'])} OWNED BY "
                f"{qname(r['owner_schema'], r['owner_table'])}.{ident(r['owner_col'])}"
            )
        self.table_names = {(r["nspname"], r["relname"]) for r in rels}
        return count

    def constraints(self):
        rows = self.c.query(
            "select n.nspname, c.relname, con.conname, con.contype, "
            "pg_get_constraintdef(con.oid) as def "
            "from pg_constraint con "
            "join pg_class c on c.oid = con.conrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            f"where n.nspname in ({self.s_in}) and con.contype in ('p', 'u', 'c', 'x', 'f') "
            "and not exists (select 1 from pg_depend d where d.objid = con.oid "
            "  and d.classid = 'pg_constraint'::regclass and d.deptype = 'e') "
            "order by n.nspname, c.relname, con.contype, con.conname"
        )
        local = [r for r in rows if r["contype"] != "f"]
        fks = [r for r in rows if r["contype"] == "f"]
        self.banner("Primary keys, unique and check constraints")
        for r in local:
            self.emit(
                f"ALTER TABLE {qname(r['nspname'], r['relname'])} "
                f"ADD CONSTRAINT {ident(r['conname'])} {r['def']}"
            )
        self.banner("Foreign keys")
        for r in fks:
            self.emit(
                f"ALTER TABLE {qname(r['nspname'], r['relname'])} "
                f"ADD CONSTRAINT {ident(r['conname'])} {r['def']}"
            )
        return len(local), len(fks)

    def views(self):
        rows = self.c.query(
            "select n.nspname, c.relname, c.relkind, pg_get_viewdef(c.oid, true) as def "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            f"where n.nspname in ({self.s_in}) and c.relkind in ('v', 'm') "
            "and not exists (select 1 from pg_depend d where d.objid = c.oid "
            "  and d.classid = 'pg_class'::regclass and d.deptype = 'e') "
            "order by c.relkind, 1, 2"
        )
        deps = self.c.query(
            "select distinct sn.nspname as src_schema, sc.relname as src, "
            "tn.nspname as tgt_schema, tc.relname as tgt "
            "from pg_rewrite r "
            "join pg_class sc on sc.oid = r.ev_class "
            "join pg_namespace sn on sn.oid = sc.relnamespace "
            "join pg_depend d on d.objid = r.oid and d.classid = 'pg_rewrite'::regclass "
            "join pg_class tc on tc.oid = d.refobjid and tc.relkind in ('v', 'm') "
            "join pg_namespace tn on tn.oid = tc.relnamespace "
            f"where sn.nspname in ({self.s_in}) and tn.nspname in ({self.s_in}) "
            "and sc.relkind in ('v', 'm') and sc.oid <> tc.oid"
        )
        # topological sort: a view is emitted after the views it selects from
        need = defaultdict(set)
        for d in deps:
            need[(d["src_schema"], d["src"])].add((d["tgt_schema"], d["tgt"]))
        pending = OrderedDict(((r["nspname"], r["relname"]), r) for r in rows)
        ordered = []
        while pending:
            progressed = False
            for key in list(pending):
                if not (need[key] & set(pending)):
                    ordered.append(pending.pop(key))
                    progressed = True
            if not progressed:  # cycle: emit in catalog order
                ordered.extend(pending.values())
                break
        self.banner("Views and materialized views")
        n_v = n_m = 0
        for r in ordered:
            body = r["def"].strip().rstrip(";")
            if r["relkind"] == "m":
                self.emit(f"CREATE MATERIALIZED VIEW IF NOT EXISTS {qname(r['nspname'], r['relname'])} AS\n{body}")
                self.note(f"{r['relname']} is populated by REFRESH MATERIALIZED VIEW, not by this file")
                n_m += 1
            else:
                self.emit(f"CREATE OR REPLACE VIEW {qname(r['nspname'], r['relname'])} AS\n{body}")
                n_v += 1
            self.out.append("")
        if not ordered:
            self.note("(no views)")
        return n_v, n_m

    def functions(self):
        rows = self.c.query(
            "select n.nspname, p.proname, p.oid::regprocedure::text as sig, p.prokind, "
            "pg_get_function_identity_arguments(p.oid) as args, "
            "(p.prorettype = 'trigger'::regtype) as is_trigger_fn, "
            "case when p.prokind in ('f', 'p') then pg_get_functiondef(p.oid) end as def "
            "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            f"where n.nspname in ({self.s_in}) "
            "and not exists (select 1 from pg_depend d where d.objid = p.oid "
            "  and d.classid = 'pg_proc'::regclass and d.deptype = 'e') "
            "order by (p.prorettype = 'trigger'::regtype) desc, n.nspname, p.proname, p.oid"
        )
        self.banner("Functions (trigger functions first, so the triggers below resolve)")
        count = 0
        for r in rows:
            if not r["def"]:
                self.note(f"WARNING: skipped {r['prokind']}-kind routine {r['sig']} "
                          "(pg_get_functiondef does not support it)")
                continue
            body = r["def"].strip()
            if not body.endswith(";"):
                body += ";"
            self.out.append(body)
            self.out.append("")
            count += 1
        self.function_sigs = [r["sig"] for r in rows if r["def"]]
        return count

    def triggers(self):
        rows = self.c.query(
            "select n.nspname, c.relname, t.tgname, pg_get_triggerdef(t.oid) as def "
            "from pg_trigger t "
            "join pg_class c on c.oid = t.tgrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            f"where n.nspname in ({self.s_in}) and not t.tgisinternal "
            "and not exists (select 1 from pg_depend d where d.objid = t.oid "
            "  and d.classid = 'pg_trigger'::regclass and d.deptype = 'e') "
            "order by 1, 2, 3"
        )
        self.banner("Triggers")
        for r in rows:
            self.emit(r["def"])
        return len(rows)

    def indexes(self):
        rows = self.c.query(
            "select i.schemaname, i.tablename, i.indexname, i.indexdef "
            "from pg_indexes i "
            f"where i.schemaname in ({self.s_in}) "
            "and not exists (select 1 from pg_constraint con "
            "  join pg_class ic on ic.oid = con.conindid "
            "  join pg_namespace cn on cn.oid = ic.relnamespace "
            "  where ic.relname = i.indexname and cn.nspname = i.schemaname) "
            "order by 1, 2, 3"
        )
        self.banner("Indexes not backed by a constraint")
        for r in rows:
            definition = r["indexdef"]
            definition = re.sub(r"^CREATE (UNIQUE )?INDEX ", r"CREATE \1INDEX IF NOT EXISTS ", definition)
            self.emit(definition)
        return len(rows)

    def rls(self):
        rows = self.c.query(
            "select n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            f"where n.nspname in ({self.s_in}) and c.relkind in ('r', 'p') "
            "and (c.relrowsecurity or c.relforcerowsecurity) "
            "order by 1, 2"
        )
        self.banner("Row level security")
        for r in rows:
            if r["relrowsecurity"]:
                self.emit(f"ALTER TABLE {qname(r['nspname'], r['relname'])} ENABLE ROW LEVEL SECURITY")
            if r["relforcerowsecurity"]:
                self.emit(f"ALTER TABLE {qname(r['nspname'], r['relname'])} FORCE ROW LEVEL SECURITY")
        return len(rows)

    def policies(self):
        rows = self.c.query(
            "select schemaname, tablename, policyname, permissive, roles::text as roles, cmd, "
            "qual, with_check from pg_policies "
            f"where schemaname in ({self.s_in}) order by 1, 2, 3"
        )
        self.banner("Policies")
        for r in rows:
            roles = [x.strip() for x in r["roles"].strip("{}").split(",") if x.strip()]
            roles_sql = ", ".join("PUBLIC" if x == "-" else ident(x) for x in roles) or "PUBLIC"
            stmt = [f"CREATE POLICY {ident(r['policyname'])} ON {qname(r['schemaname'], r['tablename'])}"]
            stmt.append(f"    AS {r['permissive'].upper()}")
            stmt.append(f"    FOR {r['cmd'].upper()}")
            stmt.append(f"    TO {roles_sql}")
            if r["qual"]:
                stmt.append(f"    USING ({r['qual']})")
            if r["with_check"]:
                stmt.append(f"    WITH CHECK ({r['with_check']})")
            self.emit("\n".join(stmt))
        return len(rows)

    def grants(self):
        g_in = in_list(GRANTEES)
        table_rows = self.c.query(
            "select table_schema, table_name, grantee, "
            "string_agg(distinct privilege_type, ', ' order by privilege_type) as privs "
            "from information_schema.role_table_grants "
            f"where table_schema in ({self.s_in}) and grantee in ({g_in}) "
            "group by 1, 2, 3 order by 1, 2, 3"
        )
        # information_schema does not list materialized views; read their ACLs directly.
        matview_rows = self.c.query(
            "select n.nspname as table_schema, c.relname as table_name, "
            "a.grantee::regrole::text as grantee, "
            "string_agg(distinct a.privilege_type, ', ' order by a.privilege_type) as privs "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "cross join lateral aclexplode(c.relacl) a "
            f"where n.nspname in ({self.s_in}) and c.relkind = 'm' "
            f"and a.grantee::regrole::text in ({g_in}) "
            "group by 1, 2, 3 order by 1, 2, 3"
        )
        func_rows = self.c.query(
            "select n.nspname, p.oid::regprocedure::text as sig, p.prokind, "
            "a.grantee::regrole::text as grantee, "
            "string_agg(distinct a.privilege_type, ', ' order by a.privilege_type) as privs "
            "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "cross join lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a "
            f"where n.nspname in ({self.s_in}) "
            "and not exists (select 1 from pg_depend d where d.objid = p.oid "
            "  and d.classid = 'pg_proc'::regclass and d.deptype = 'e') "
            f"and a.grantee::regrole::text in ({g_in}) "
            "group by 1, 2, 3, 4 order by 1, 2, 4"
        )
        self.banner("Grants (anon, authenticated, service_role)")
        for r in list(table_rows) + list(matview_rows):
            self.emit(
                f"GRANT {r['privs']} ON TABLE {qname(r['table_schema'], r['table_name'])} "
                f"TO {ident(r['grantee'])}"
            )
        self.out.append("")
        for r in func_rows:
            kind = "PROCEDURE" if r["prokind"] == "p" else "FUNCTION"
            self.emit(f"GRANT {r['privs']} ON {kind} {r['sig']} TO {ident(r['grantee'])}")
        return len(table_rows) + len(matview_rows), len(func_rows)

    def comments(self):
        rel_rows = self.c.query(
            "select n.nspname, c.relname, c.relkind, d.description "
            "from pg_description d "
            "join pg_class c on c.oid = d.objoid "
            "join pg_namespace n on n.oid = c.relnamespace "
            f"where d.objsubid = 0 and n.nspname in ({self.s_in}) and c.relkind in ('r', 'p', 'v', 'm') "
            "order by 1, 2"
        )
        col_rows = self.c.query(
            "select n.nspname, c.relname, a.attname, d.description "
            "from pg_description d "
            "join pg_class c on c.oid = d.objoid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "join pg_attribute a on a.attrelid = c.oid and a.attnum = d.objsubid "
            f"where d.objsubid > 0 and n.nspname in ({self.s_in}) and c.relkind in ('r', 'p', 'v', 'm') "
            "order by 1, 2, a.attnum"
        )
        fn_rows = self.c.query(
            "select p.oid::regprocedure::text as sig, p.prokind, d.description "
            "from pg_description d "
            "join pg_proc p on p.oid = d.objoid "
            "join pg_namespace n on n.oid = p.pronamespace "
            f"where n.nspname in ({self.s_in}) "
            "and not exists (select 1 from pg_depend dd where dd.objid = p.oid "
            "  and dd.classid = 'pg_proc'::regclass and dd.deptype = 'e') "
            "order by 1"
        )
        self.banner("Comments")
        total = 0
        for r in rel_rows:
            kind = "MATERIALIZED VIEW" if r["relkind"] == "m" else ("VIEW" if r["relkind"] == "v" else "TABLE")
            self.emit(f"COMMENT ON {kind} {qname(r['nspname'], r['relname'])} IS {lit(r['description'])}")
            total += 1
        for r in col_rows:
            self.emit(
                f"COMMENT ON COLUMN {qname(r['nspname'], r['relname'])}.{ident(r['attname'])} "
                f"IS {lit(r['description'])}"
            )
            total += 1
        for r in fn_rows:
            kind = "PROCEDURE" if r["prokind"] == "p" else "FUNCTION"
            self.emit(f"COMMENT ON {kind} {r['sig']} IS {lit(r['description'])}")
            total += 1
        if not total:
            self.note("(no comments on objects in these schemas)")
        return total

    def cron_jobs(self):
        try:
            rows = self.c.query(
                "select jobid, jobname, schedule, command, active, database, username "
                "from cron.job order by jobid"
            )
        except SystemExit:
            rows = []
        self.banner("pg_cron jobs (NOT created by this migration)")
        self.note("These live in the cron schema, which this baseline deliberately does not")
        self.note("manage. Recreate them by hand (or in a dedicated migration) if you rebuild")
        self.note("the project from scratch:")
        self.note("")
        for r in rows:
            self.note(
                f"  select cron.schedule({lit(r['jobname'])}, {lit(r['schedule'])}, "
                f"{lit(r['command'].strip())});"
                + ("" if r["active"] else "  -- inactive")
            )
        self.note("")
        self.note("Known issue (follow-up, not this PR): retry_failed_jobs() does not exist in")
        self.note("the database, so that job fails on every run.")
        return len(rows)

    def run(self):
        counts = {}
        placeholder = "-- @@OBJECT_COUNTS@@"
        self.header(placeholder)
        self.schemas_section()
        counts["extensions"] = self.extensions()
        counts["enums"] = self.enums()
        counts["sequences"] = self.sequences()
        counts["tables"] = self.tables()
        counts["constraints"], counts["foreign keys"] = self.constraints()
        counts["views"], counts["materialized views"] = self.views()
        counts["functions"] = self.functions()
        counts["triggers"] = self.triggers()
        counts["indexes"] = self.indexes()
        counts["tables with RLS"] = self.rls()
        counts["policies"] = self.policies()
        counts["table grants"], counts["function grants"] = self.grants()
        counts["comments"] = self.comments()
        counts["cron jobs (commented)"] = self.cron_jobs()
        summary = ["-- Object counts in this baseline:"]
        for key, value in counts.items():
            summary.append(f"--   {key}: {value}")
        idx = self.out.index(placeholder)
        self.out[idx:idx + 1] = summary
        sys.stderr.write(f"{self.c.queries} catalog queries; "
                         + ", ".join(f"{k}={v}" for k, v in counts.items()) + "\n")
        return "\n".join(self.out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", help="file to write (default: stdout)")
    parser.add_argument("--project-ref", default=os.environ.get("SUPABASE_PROJECT_REF", DEFAULT_REF))
    parser.add_argument("--api-url", default=os.environ.get("SUPABASE_MANAGEMENT_API_URL", DEFAULT_API))
    parser.add_argument(
        "--schemas",
        default=os.environ.get("SUPABASE_BASELINE_SCHEMAS", DEFAULT_SCHEMAS),
        help="comma-separated list of schemas to dump",
    )
    args = parser.parse_args()
    schemas = [s.strip() for s in args.schemas.split(",") if s.strip()]
    sql = Dumper(Client(args.project_ref, args.api_url), schemas).run()
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(sql)
    else:
        sys.stdout.write(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
