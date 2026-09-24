from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy.schema import UniqueConstraint, CheckConstraint, PrimaryKeyConstraint, ForeignKeyConstraint

# 1. Initialize your connection engine
engine = create_engine("postgresql+psycopg://school:school@localhost:5432/school_db")

# 2. Instantiate metadata and inspector
metadata = MetaData()
metadata.reflect(bind=engine)
inspector = inspect(engine)

print("============ COMPLETE DATABASE SCHEMA MANIFEST ============")

for table_name in metadata.tables:
    print(f"\nTABLE: {table_name}")
    table_obj = metadata.tables[table_name]

    # ----------------------------------------------------
    # A. COLUMNS & DATA TYPES
    # ----------------------------------------------------
    print("  [Columns]")
    for column in table_obj.columns:
        nullable = "NULL" if column.nullable else "NOT NULL"
        default = ""
        if column.server_default:
            # Check if it is a database-calculated computed column
            if hasattr(column.server_default, 'sqltext'):
                default = f" GENERATED ALWAYS AS ({column.server_default.sqltext})"
            elif hasattr(column.server_default, 'arg'):
                default = f" DEFAULT {column.server_default.arg}"
            else:
                default = f" DEFAULT {str(column.server_default)}"
        print(f"    • {column.name:<20} {str(column.type):<15} {nullable}{default}")

    # ----------------------------------------------------
    # B. PRIMARY KEY CONSTRAINTS (Handles single & composite keys)
    # ----------------------------------------------------
    pk_constraint = inspector.get_pk_constraint(table_name)
    if pk_constraint and pk_constraint.get('constrained_columns'):
        pk_cols = ", ".join(pk_constraint['constrained_columns'])
        pk_name = pk_constraint.get('name') or 'Unnamed_PK'
        print(f"  [Primary Key]\n    • {pk_name}: ({pk_cols})")

    # ----------------------------------------------------
    # C. RELATIONS (Foreign Key Constraints)
    # ----------------------------------------------------
    fk_constraints = inspector.get_foreign_keys(table_name)
    if fk_constraints:
        print("  [Relations / Foreign Keys]")
        for fk in fk_constraints:
            fk_name = fk.get('name') or 'Unnamed_FK'
            local_cols = ", ".join(fk['constrained_columns'])
            referred_table = fk['referred_table']
            referred_cols = ", ".join(fk['referred_columns'])

            # Capture behavioral constraints
            options = fk.get('options', {})
            on_delete = f" ON DELETE {options.get('ondelete')}" if options.get('ondelete') else ""
            on_update = f" ON UPDATE {options.get('onupdate')}" if options.get('onupdate') else ""

            print(
                f"    • {fk_name}: ({local_cols}) -> REFERENCES {referred_table}({referred_cols}){on_delete}{on_update}")

    # ----------------------------------------------------
    # D. UNIQUE & CHECK CONSTRAINTS
    # ----------------------------------------------------
    # Filter out PK and FK to avoid double-printing
    other_constraints = [
        c for c in table_obj.constraints
        if not isinstance(c, (ForeignKeyConstraint, PrimaryKeyConstraint))
    ]

    if other_constraints:
        print("  [Constraints]")
        for const in other_constraints:
            if isinstance(const, UniqueConstraint):
                col_names = ", ".join([col.name for col in const.columns])
                print(f"    • UNIQUE ({const.name or 'Unnamed'}): ({col_names})")

            elif isinstance(const, CheckConstraint):
                print(f"    • CHECK ({const.name or 'Unnamed'}): {const.sqltext}")

    # ----------------------------------------------------
    # E. INDEXES (Handles performance maps & unique index rules)
    # ----------------------------------------------------
    indexes = inspector.get_indexes(table_name)
    if indexes:
        print("  [Indexes]")
        for idx in indexes:
            idx_name = idx['name']
            idx_cols = ", ".join(idx['column_names'])
            is_unique = "UNIQUE " if idx['unique'] else ""
            print(f"    • {idx_name}: {is_unique}INDEX on ({idx_cols})")

    print("-" * 60)
