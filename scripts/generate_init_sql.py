import toml
import os

TOML_PATH = os.path.join(os.path.dirname(__file__), '..', 'morphik.toml')
INIT_SQL_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '..', 'init.sql')
OUTPUT_SQL_PATH = os.path.join(os.path.dirname(__file__), '..', 'build', 'init.sql')

def main():
    # Read morphik.toml
    with open(TOML_PATH, 'r') as f:
        config = toml.load(f)
    embedding_dim = config.get('embedding', {}).get('dimensions', 1536)

    # Read init.sql template
    with open(INIT_SQL_TEMPLATE_PATH, 'r') as f:
        sql = f.read()

    # Substitute placeholder
    sql = sql.replace('{{embedding_dim}}', str(embedding_dim))

    # Ensure output directory exists
    os.makedirs(os.path.dirname(OUTPUT_SQL_PATH), exist_ok=True)

    # Write output SQL
    with open(OUTPUT_SQL_PATH, 'w') as f:
        f.write(sql)

    print(f"Generated {OUTPUT_SQL_PATH} with embedding_dim={embedding_dim}")

if __name__ == '__main__':
    main()