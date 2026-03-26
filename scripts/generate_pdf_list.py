import csv

html = """<!DOCTYPE html>
<html>
<head>
<title>Math Quiz Credentials</title>
<style>
  body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 800px; margin: 40px auto; color: #333; }
  h1 { text-align: center; color: #6c63ff; margin-bottom: 2rem; }
  table { border-collapse: collapse; width: 100%; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
  th, td { border: 1px solid #e2e8f0; padding: 12px 16px; text-align: left; }
  th { background-color: #f8fafc; font-weight: 600; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 0.05em; color: #64748b; }
  tr:nth-child(even) { background-color: #f8fafc; }
  td.pin { font-family: monospace; font-size: 1.1rem; font-weight: bold; letter-spacing: 2px; }
  .instructions { background: #eff6ff; border-left: 4px solid #3b82f6; padding: 1rem; margin-bottom: 2rem; border-radius: 4px; }
  @media print {
    body { margin: 0; max-width: 100%; }
    .instructions { display: none; }
    table { box-shadow: none; }
  }
</style>
</head>
<body>
  <div class="instructions">
    <strong>Instructions:</strong> Press <code>Ctrl + P</code> (Windows) or <code>Cmd + P</code> (Mac) to print this page and select "Save as PDF".
  </div>
  <h1>Math Quiz — Team Credentials</h1>
  <table>
    <tr>
      <th>Team ID</th>
      <th>Login PIN</th>
    </tr>
"""

try:
    with open('credentials.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            html += f"""
    <tr>
      <td>{row['team_id']}</td>
      <td class="pin">{row['pin']}</td>
    </tr>"""
except FileNotFoundError:
    print("credentials.csv not found.")

html += """
  </table>
</body>
</html>
"""

with open('credentials_list.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Successfully generated credentials_list.html!")
