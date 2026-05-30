{#
  generate_schema_name.sql
  ─────────────────────────
  Override dbt's default schema-name generation.

  Default behaviour would produce names like  main_staging, main_marts, etc.
  This macro makes the schema name exactly the custom_schema_name when one is
  specified, so models land in  staging, intermediate, marts  (no prefix).

  See: https://docs.getdbt.com/docs/build/custom-schemas
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {%- if custom_schema_name is none -%}
    {{ target.schema }}
  {%- else -%}
    {{ custom_schema_name | trim }}
  {%- endif -%}
{%- endmacro %}
