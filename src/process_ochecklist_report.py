import os
import shutil
import sys
import ftplib
import html
import re
import yaml
from typing import Tuple
from io import StringIO
from datetime import datetime

"""
Process report from the mobile app O-checklist and create html report with changes that can be ticked as done
Usage: All orienteering events with startlist in iof-xml v3.0
"""

def main() -> None:
    # parse config file name from argument[1]
    config_file_name = parse_args()
    print(f"Config file is " + config_file_name + ".\n")
    # read YAML config file
    try:
        with open(config_file_name, "r") as yamlfile:
            cfg = yaml.safe_load(yamlfile)
    except Exception as inst:
        print(inst)    # the exception type
        exit()
    # set FTP server configuration
    ftp_server_credentials = cfg['ftp_server_credentials']
    # set HTML output configuration
    html_config = cfg['html_config']

    output_dir = html_config.get('output_dir', '.')

    downloaded_file = download_file_from_ftp(**ftp_server_credentials)
    changes = process_downloaded_yaml(downloaded_file)
    generate_html_report(changes, html_config['report_name'], output_dir)
    if(html_config['ftp_upload']):
        upload_file_to_ftp(ftp_server_credentials['server'],ftp_server_credentials['login'], ftp_server_credentials['password'], html_config['subfolder'], html_config['report_name'], output_dir)
        print(f"HTML file " + html_config['report_name'] + ".html has been uploaded to FTP server.\n")
    else:
        print(f"HTML file " + html_config['report_name'] + ".html has been stored.\n")

def upload_file_to_ftp(server , login, password, subfolder='/', report_name = 'online-report', output_dir='.'):
    """
    Post file to ftp server
    :param server: ftp server
    :param login: Username
    :param password: password
    :param subfolder: downloaded file location
    :param report_name: uploaded file name
    :param output_dir: local directory the report was written to
    """

    # Connect to the FTP server
    ftp = ftplib.FTP(server, login, password)

    # Change to the directory where the file is located (if necessary)
    ftp.cwd(subfolder)

    # Open the local html file
    file = open(os.path.join(output_dir, report_name+".html"),'rb')
    # Store to FTP server
    ftp.storbinary('STOR ' + report_name+".html", file)
    # Cloce the local html file
    file.close()
    # Close the FTP connection
    ftp.quit()

def download_file_from_ftp(server, login, password, subfolder='/'):
    """
    Get file from ftp server
    :param server: ftp server
    :param login: Username
    :param password: password
    :param subfolder: downloaded file location
    :return: list of list wirh filename and downloaded file content
    """

    downloaded_files = []
    # Connect to the FTP server
    ftp = ftplib.FTP(server, login, password)

    # Change to the directory where the file is located (if necessary)
    ftp.cwd(subfolder)

    # Download the file from the FTP server and write it to the StringIO object
    def write_file_data(data):
        downloaded_file.write(data.decode('utf-8'))

    # Get a list of all YAML files in the directory
    filenames = ftp.nlst('*.yaml')
    for filename in filenames:
        # Create a StringIO object to hold the contents of the downloaded file
        downloaded_file = StringIO()

        # Download the file
        ftp.retrbinary('RETR ' + filename, write_file_data)

        # Retrieve the contents of the StringIO object as a string
        downloaded_files.append([filename, downloaded_file.getvalue()])

    # Close the FTP connection
    ftp.quit()

    return downloaded_files

def process_downloaded_yaml(downloaded_files):
    """
    Iterates over all downloaded file and separates changes - dns, late starts, changes cards and new comments
    :param downloaded_files: list of lists with filename and contents of downloaded yaml files
    :return: dictionary of lists with changes by type
    """

    # Results storage
    started_ok = []
    changes_cards = []
    changes_dns = []
    changes_late_start = []
    changes_comments = []
    changes_statistics = []

    changes = {}

    # Parse every file up front and process them in chronological order (by
    # their own 'Created' timestamp) rather than in whatever order the FTP
    # server happens to list them in - the cumulative statistics below rely
    # on files being processed oldest-first.
    parsed_files = [(filename, yaml.safe_load(content)) for filename, content in downloaded_files]
    parsed_files.sort(key=lambda item: item[1]['Created'])

    for filename, downloaded_data in parsed_files:
        # Access report data
        report_data = downloaded_data['Data']
        for runner in report_data:
            runner_info = runner['Runner']
            # Values
            runner_id = runner_info['Id'] if runner_info['Id'] is not None else ''
            # StartTime may be absent depending on the app/export version -
            # fall back to None instead of raising KeyError so a single
            # missing field doesn't abort processing of the whole report.
            runner_start_time = runner_info.get('StartTime')
            runner_class_name = runner_info['ClassName']
            runner_name = runner_info['Name'] if runner_info['Name'] is not None else ''
            runner_club = runner_info['Org'] if runner_info['Org'] is not None else ''
            runner_card = runner_info['Card'] if runner_info['Card'] is not None else ''

            if runner['ChangeLog'] is not None:
                # New card
                if 'NewCard' in runner_info:
                    changes_cards.append([
                        runner_id,
                        runner_start_time,
                        runner['ChangeLog']['NewCard'],
                        runner_name,
                        runner_class_name,
                        runner_club,
                        runner_card,
                        runner_info['NewCard']
                    ])
                # # DNS
                if 'DNS' in runner_info['StartStatus']:
                    changes_dns.append([
                        runner_id,
                        runner_start_time,
                        runner['ChangeLog']['DNS'],
                        runner_name,
                        runner_class_name,
                        runner_club,
                        runner_card
                    ])
                # # Late start
                if 'Late start' in runner_info['StartStatus']:
                    changes_late_start.append([
                        runner_id,
                        runner_start_time,
                        runner['ChangeLog']['LateStart'],
                        runner_name,
                        runner_class_name,
                        runner_club,
                        runner_card
                    ])
                # # Comment
                if 'Comment' in runner_info:
                    changes_comments.append([
                        runner_id,
                        runner_start_time,
                        runner['ChangeLog']['Comment'],
                        runner_name,
                        runner_class_name,
                        runner_club,
                        runner_card,
                        runner_info['Comment']
                    ])

            # Store started runners
            else:
                started_ok.append(runner_name + ', ' + runner_class_name + ', ' + runner_club)
        # Store statistics
        stats = {'ok': len(started_ok),
                 'dns': len(changes_dns),
                 'card-changes': len(changes_cards),
                 'late-starts': len(changes_late_start),
                 'comments': len(changes_comments)}
        changes_statistics.append([filename, downloaded_data['Created'], downloaded_data['Creator'], downloaded_data['Version'], stats]);

    # Store into the main dictionary
    changes['dns'] = changes_dns
    changes['changed_cards'] = changes_cards
    changes['late_starts'] = changes_late_start
    changes['comments'] = changes_comments
    changes['statistics'] = changes_statistics

    # Print statistics
    print(f"Event statistics:\n"
          f"- started runners: {len(started_ok)}\n"
          f"- dns: {len(changes_dns)}\n"
          f"- cards changes: {len(changes_cards)}\n"
          f"- late starts: {len(changes_late_start)}\n"
          f"- new comments: {len(changes_comments)}")

    return changes

def format_time(value, fmt='%H:%M:%S'):
    """
    Format a datetime for display, tolerating missing values (e.g. a runner
    with no recorded StartTime) instead of raising an exception.
    """
    return value.strftime(fmt) if value else '-'

def make_row_id(*parts):
    """
    Build a safe, unique HTML id from row-identifying values. Including the
    runner id keeps rows unique even when two runners share a class and
    start time; non-id-safe characters (spaces, diacritics, ...) coming
    from free-text fields like class name are sanitized out.
    """
    raw = '-'.join(str(part) for part in parts if part not in (None, ''))
    slug = re.sub(r'[^A-Za-z0-9_-]+', '_', raw) or 'unknown'
    return f"row-{slug}"

def render_table(table_id, header_defs, body_rows, empty_message, colspan):
    """
    Render a <table> with a sortable header row and the given body rows, or
    a single 'no data' row when body_rows is empty. Shared by every changes
    table so header/empty-state handling only needs to be correct in one
    place.
    :param table_id: id attribute of the table, also used by sortTable()
    :param header_defs: list of (css_class, label) tuples for sortable columns
    :param body_rows: list of already-built <tr>...</tr> HTML strings
    :param empty_message: text shown when there is no data
    :param colspan: colspan of the empty-state row
    """
    if not body_rows:
        body = f"<tr><td class='nodata' colspan='{colspan}'>{html.escape(empty_message)}</td></tr>"
    else:
        header_cells = ''.join(
            f'<th onclick="sortTable({index}, \'{table_id}\')" class=\'{css_class}\'>{html.escape(label)}</th>'
            for index, (css_class, label) in enumerate(header_defs)
        )
        body = f"<tr>{header_cells}</tr>" + ''.join(body_rows)
    return f"<table id='{table_id}'>{body}</table>"

def render_change_row(row_id, cells):
    """
    Render one data row with a leading 'solved' checkbox cell. Every value
    is HTML-escaped since it may contain free text entered by a starter
    (name, club, comment) that must never be interpreted as markup.
    :param row_id: sanitized id attribute for the <tr>
    :param cells: list of (css_class, value) tuples rendered in order
    """
    tds = ''.join(
        f"<td class='{css_class}'>{html.escape(str(value)) if value is not None else ''}</td>"
        for css_class, value in cells
    )
    return f'<tr id="{row_id}"><td><input type="checkbox" class="solved"></td>{tds}</tr>'

def resource_path(filename):
    """
    Resolve the path to a bundled report asset (style.css, main.js), both
    when running from source (assets live next to this script) and when
    running as a PyInstaller-frozen executable (assets are unpacked into a
    temporary 'assets' folder alongside the bundle).
    """
    if getattr(sys, 'frozen', False):
        base_path = os.path.join(sys._MEIPASS, 'assets')
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, filename)

def ensure_report_assets(output_dir):
    """
    Make sure style.css and main.js are available next to the generated
    report at <output_dir>/src/, since the report links to them with a
    relative path. Existing files are left untouched so local
    customizations survive repeated report generation.
    """
    assets_dir = os.path.join(output_dir, 'src')
    os.makedirs(assets_dir, exist_ok=True)
    for asset in ('style.css', 'main.js'):
        destination = os.path.join(assets_dir, asset)
        if not os.path.exists(destination):
            shutil.copyfile(resource_path(asset), destination)

def generate_html_report(changes, report_name = 'online-report', output_dir = '.'):
    """
    Create html report with changes from the start in hrml format which is more readable.
    :param changes:
    :param report_name: base file name (without extension) of the generated report
    :param output_dir: directory the report (and its src/ assets) is written to
    :return: html_file
    """

    ensure_report_assets(output_dir)

    html_file_template = '''
        <!DOCTYPE html>
        <html>
            <head>
                <meta name="description" content="Report with changes from the start of orienteering event">
                <meta name="keywords" content="ochecklist, orienteering, start, report">
                <meta name="author" content="Lukas Kettner, OK Kamenice">
                <meta http-equiv='Content-Type' content='text/html; charset=utf-8' />
                <meta name="viewport" content="width=device-width, initial-scale=1.0" />
                <!-- TODO: Can be used instead of live-server -->
                <!--<meta http-equiv="refresh" content="30"> -->
                <link rel="stylesheet" href="src/style.css">
                <title>{heading}</title>
            </head>
            <body onload="sortTable(0, 'dataDNS'),sortTable(0, 'dataCards'),sortTable(0, 'dataLateStart'),sortTable(0, 'dataComments'),sortTable(0, 'dataStatistics')">
                <header>
                    <h1>{heading}</h1>
                    <h2>{time_stamp}</h2>
                </header>
                <!-- Did not start (DNS) -->
                <section>{content_dns}</section>

                <!-- Card canges -->
                <section>{content_cards}</section>

                <!-- Late starts -->
                <section>{content_late_start}</section>

                <!-- Comments -->
                <section>{content_comments}</section>

                <!-- Stats -->
                <section>{content_statistics}</section>

                <footer>
                    <p>Created with script by Cáš based on report from O Checklist mobile app.</p>
                </footer>
                <script type="text/javascript" src="src/main.js"></script>
            </body>
        </html>
    '''

    # DNS
    dns_headers = [
        ('solved', 'Vyřešeno'),
        ('timestamp', 'Čas změny'),
        ('starttime', 'Star. čas'),
        ('name', 'Jméno'),
        ('class', 'Kategorie'),
        ('club', 'Klub'),
        ('card', 'Čip'),
    ]
    dns_rows = []
    for dns in changes['dns']:
        row_id = make_row_id(dns[0], dns[1], dns[4])
        cells = [
            ('timestamp', format_time(dns[2])),
            ('starttime', format_time(dns[1])),
            ('name', dns[3]),
            ('class', dns[4]),
            ('club', dns[5]),
            ('card', dns[6]),
        ]
        dns_rows.append(render_change_row(row_id, cells))
    dns_changes_html = render_table('dataDNS', dns_headers, dns_rows, 'Žadní neběžící závodníci a závodnice.', 4)

    # Cards
    cards_headers = [
        ('solved', 'Vyřešeno'),
        ('timestamp', 'Čas změny'),
        ('starttime', 'Star. čas'),
        ('name', 'Jméno'),
        ('class', 'Kategorie'),
        ('club', 'Klub'),
        ('oldcard', 'Starý čip'),
        ('card', 'Nový čip'),
    ]
    cards_rows = []
    for card in changes['changed_cards']:
        row_id = make_row_id(card[0], card[1], card[4])
        cells = [
            ('timestamp', format_time(card[2])),
            ('starttime', format_time(card[1])),
            ('name', card[3]),
            ('class', card[4]),
            ('club', card[5]),
            ('oldcard', card[6]),
            ('card', card[7]),
        ]
        cards_rows.append(render_change_row(row_id, cells))
    cards_changes_html = render_table('dataCards', cards_headers, cards_rows, 'Žadné změny čipů.', 5)

    # Late starts
    late_start_headers = [
        ('solved', 'Vyřešeno'),
        ('timestamp', 'Čas změny'),
        ('starttime', 'Star. čas'),
        ('name', 'Jméno'),
        ('class', 'Kategorie'),
        ('club', 'Klub'),
        ('card', 'Čip'),
    ]
    late_start_rows = []
    for late_start in changes['late_starts']:
        row_id = make_row_id(late_start[0], late_start[1], late_start[4])
        cells = [
            ('timestamp', format_time(late_start[2])),
            ('starttime', format_time(late_start[1])),
            ('name', late_start[3]),
            ('class', late_start[4]),
            ('club', late_start[5]),
            ('card', late_start[6]),
        ]
        late_start_rows.append(render_change_row(row_id, cells))
    late_starts_changes_html = render_table('dataLateStart', late_start_headers, late_start_rows, 'Žadné opožděné starty.', 4)

    # Comments
    comments_headers = [
        ('solved', 'Vyřešeno'),
        ('timestamp', 'Čas změny'),
        ('starttime', 'Star. čas'),
        ('name', 'Jméno'),
        ('class', 'Kategorie'),
        ('club', 'Klub'),
        ('card', 'Čip'),
        ('comment', 'Komentář'),
    ]
    comments_rows = []
    for comment in changes['comments']:
        row_id = make_row_id(comment[0], comment[1], comment[4])
        cells = [
            ('timestamp', format_time(comment[2])),
            ('starttime', format_time(comment[1])),
            ('name', comment[3]),
            ('class', comment[4]),
            ('club', comment[5]),
            ('card', comment[6]),
            ('comment', comment[7]),
        ]
        comments_rows.append(render_change_row(row_id, cells))
    comments_changes_html = render_table('dataComments', comments_headers, comments_rows, 'Žádné nové komentáře.', 5)

    # Statistics
    statistics_headers = [
        ('filename', 'Název souboru'),
        ('created', 'Datum vytvoření'),
        ('creator', 'Verze aplikace'),
        ('version', 'Verze reportu'),
        ('ok', 'OK'),
        ('dns', 'DNS'),
        ('new-cards', 'New cards'),
        ('late-starts', 'Late starts'),
        ('new-comments', 'New comments'),
    ]
    statistics_rows = []
    previous_stats = None
    for filename, created, creator, version, stats in changes['statistics']:
        display_stats = stats if previous_stats is None else {
            key: value - previous_stats[key] for key, value in stats.items()
        }
        cells = [
            ('file', filename),
            ('created', format_time(created)),
            ('creator', creator),
            ('version', version),
            ('ok', display_stats['ok']),
            ('dns', display_stats['dns']),
            ('new-cards', display_stats['card-changes']),
            ('late-starts', display_stats['late-starts']),
            ('new-comments', display_stats['comments']),
        ]
        tds = ''.join(
            f"<td class='{css_class}'>{html.escape(str(value))}</td>" for css_class, value in cells
        )
        statistics_rows.append(f'<tr>{tds}</tr>')
        previous_stats = stats
    statistics_changes_html = render_table('dataStatistics', statistics_headers, statistics_rows, 'Žádné statistiky.', 5)

    # Generate html report
    html_file = html_file_template.format(heading='O Checklist report',
                                          time_stamp=datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
                                          content_dns=dns_changes_html,
                                          content_cards=cards_changes_html,
                                          content_late_start=late_starts_changes_html,
                                          content_comments=comments_changes_html,
                                          content_statistics=statistics_changes_html)
    # Write the HTML to a file
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, report_name+".html"), "w", encoding='utf-8') as f:
        f.write(html_file)

    return html_file

# Not used yet, under development
def parse_args() -> Tuple[int, str]:
    """
    Parse input arguments
    """
    if len(sys.argv) != 2:
        program = sys.argv[0]
        print(f"Usage: {program} <config_file>", file=sys.stderr)
        sys.exit(1)
    return sys.argv[1]

if __name__ == "__main__":
    main()
