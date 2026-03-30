"""
Notifica Mapping Tool - Streamlit Application

Maps Taken, Winst & Verlies, and Balans data against historical mappings.
Includes self-learning capabilities that improve over time.
"""
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import pytz
import streamlit as st

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.taken_mapper import TakenMapper
from src.wv_balans_mapper import WVBalansMapper
from src.learning import LearningStore, LearningEnhancedMatcher, export_learned_mappings_to_csv
from src.utils import (
    read_csv_robust,
    get_output_filename,
    extract_base_name,
    is_mapping_file,
    get_file_type,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Base path for NotificaRAAS data
_WINDOWS_DEFAULT = r"C:\Users\tobia\OneDrive - Notifica B.V\Documenten - Sharepoint Notifica intern\102. Klantmappen\0000 - NotificaRAAS"
_LINUX_DEFAULT = os.path.join(str(Path(__file__).parent), "data")
DATA_BASE_PATH = os.environ.get(
    "RAAS_DATA_PATH",
    _WINDOWS_DEFAULT if sys.platform == "win32" else _LINUX_DEFAULT,
)

# Output directories
OUTPUT_DIRS = {
    'WV': os.path.join(DATA_BASE_PATH, 'CoA_mappings'),
    'Balans': os.path.join(DATA_BASE_PATH, 'CoA_mappings_balans'),
    'Taken': os.path.join(DATA_BASE_PATH, 'Taken_mappings'),
}

# Source directory for all mapping files
GENERATED_FILES_DIR = os.path.join(DATA_BASE_PATH, 'generated_mapping_files')

# Learning data directory
LEARNING_DIR = os.path.join(DATA_BASE_PATH, 'learning_data')

# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

st.set_page_config(
    page_title="Notifica Mapping Tool",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .stat-box {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .success-box {
        background-color: #d4edda;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #c3e6cb;
    }
    .warning-box {
        background-color: #fff3cd;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #ffc107;
    }
    .error-box {
        background-color: #f8d7da;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #f5c6cb;
    }
    .learning-badge {
        background-color: #e7f3ff;
        color: #0066cc;
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
        font-size: 0.8rem;
    }
    .confidence-high { color: #28a745; }
    .confidence-medium { color: #ffc107; }
    .confidence-low { color: #dc3545; }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# INITIALIZE LEARNING STORE
# =============================================================================

@st.cache_resource
def get_learning_store():
    """Get or create the learning store instance."""
    try:
        return LearningStore(LEARNING_DIR)
    except (PermissionError, OSError):
        import tempfile
        fallback = os.path.join(tempfile.gettempdir(), 'mappingtool_learning')
        return LearningStore(fallback)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_available_mapping_files(mapping_type: str) -> list:
    """Get list of available mapping files (1000_...) for the given type."""
    if not os.path.exists(GENERATED_FILES_DIR):
        return []

    files = []
    type_patterns = {
        'WV': 'wv_rubrieken',
        'Balans': 'balans_rubrieken',
        'Taken': 'taken',
    }

    pattern = type_patterns.get(mapping_type, '').lower()

    for filename in os.listdir(GENERATED_FILES_DIR):
        if filename.startswith('1000_') and pattern in filename.lower() and filename.endswith('.csv'):
            files.append(filename)

    # Sort by date (newest first)
    files.sort(reverse=True)
    return files


def get_available_target_files(mapping_type: str) -> list:
    """Get list of available target files (not 1000_...) for the given type."""
    if not os.path.exists(GENERATED_FILES_DIR):
        return []

    files = []
    type_patterns = {
        'WV': 'wv_rubrieken',
        'Balans': 'balans_rubrieken',
        'Taken': 'taken',
    }

    pattern = type_patterns.get(mapping_type, '').lower()

    for filename in os.listdir(GENERATED_FILES_DIR):
        if not filename.startswith('1000_') and pattern in filename.lower() and filename.endswith('.csv'):
            files.append(filename)

    # Sort by date (newest first)
    files.sort(reverse=True)
    return files


def load_file_preview(file_path: str, n_rows: int = 5) -> Optional[pd.DataFrame]:
    """Load first n rows of a file for preview."""
    try:
        df, _ = read_csv_robust(file_path)
        return df.head(n_rows)
    except Exception as e:
        st.error(f"Error loading file: {e}")
        return None


def get_confidence_class(confidence: float) -> str:
    """Get CSS class for confidence level."""
    if confidence >= 0.85:
        return "confidence-high"
    elif confidence >= 0.60:
        return "confidence-medium"
    else:
        return "confidence-low"


# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    # Initialize learning store
    learning_store = get_learning_store()

    # Header
    st.markdown('<div class="main-header">Notifica Mapping Tool</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Map nieuwe klantdata tegen historische mappings - met zelflerende AI</div>', unsafe_allow_html=True)

    # Sidebar - Navigation
    with st.sidebar:
        st.header("Navigatie")

        page = st.radio(
            "Selecteer pagina:",
            ["Mapping Tool", "Review & Correcties", "Learning Dashboard"],
            help="Navigeer tussen de verschillende functies"
        )

        st.divider()

        if page == "Mapping Tool":
            # Mapping Type Selection
            st.header("Configuratie")

            mapping_type = st.radio(
                "Selecteer mapping type:",
                ["Taken", "Winst & Verlies", "Balans"],
                help="Kies het type data dat je wilt mappen"
            )

            # Convert display name to internal name
            type_map = {
                "Taken": "Taken",
                "Winst & Verlies": "WV",
                "Balans": "Balans",
            }
            internal_type = type_map[mapping_type]

            st.divider()

            # Min fill rate setting
            min_fill_rate = st.slider(
                "Minimum fill rate (%)",
                min_value=50,
                max_value=100,
                value=90,
                help="Minimaal percentage rijen dat gemapt moet worden"
            )

            # Learning mode toggle
            use_learning = st.checkbox(
                "Gebruik geleerde mappings",
                value=True,
                help="Pas correcties uit het verleden toe op nieuwe mappings"
            )

            st.divider()

            # Info about output directories
            if os.path.exists(OUTPUT_DIRS[internal_type]):
                st.subheader("Output locaties")
                st.info(f"**{mapping_type}** output gaat naar:\n\n`{OUTPUT_DIRS[internal_type]}`")

            # Show learning stats summary
            stats = learning_store.get_statistics()
            if stats['total_learned_mappings'] > 0:
                st.success(f"**{stats['total_learned_mappings']}** geleerde mappings beschikbaar")
        else:
            internal_type = "Taken"
            min_fill_rate = 90
            use_learning = True

    # Route to the correct page
    if page == "Mapping Tool":
        show_mapping_tool(learning_store, internal_type, min_fill_rate / 100.0, use_learning)
    elif page == "Review & Correcties":
        show_review_page(learning_store)
    else:
        show_learning_dashboard(learning_store)


def show_mapping_tool(learning_store, internal_type, min_fill_rate, use_learning):
    """Show the main mapping tool interface."""

    # Main content area
    col1, col2 = st.columns(2)

    # Left column - Mapping file selection
    with col1:
        st.subheader("1. Mapping Bestand (Bron)")
        st.caption("Dit bestand bevat de historische mappings van alle klanten (1000_...)")

        has_local_files = os.path.exists(GENERATED_FILES_DIR)
        source_options = ["Selecteer bestaand bestand", "Upload bestand"] if has_local_files else ["Upload bestand"]

        mapping_source = st.radio(
            "Mapping bestand bron:",
            source_options,
            key="mapping_source",
            horizontal=True
        )

        mapping_file_path = None
        mapping_file_content = None
        mapping_filename = None

        if mapping_source == "Selecteer bestaand bestand":
            available_mappings = get_available_mapping_files(internal_type)

            if available_mappings:
                # Filter to show only "alle_klanten" files
                alle_klanten_files = [f for f in available_mappings if 'alle_klanten' in f.lower()]

                if alle_klanten_files:
                    selected_mapping = st.selectbox(
                        "Kies mapping bestand:",
                        alle_klanten_files,
                        help="Bestanden met 'alle_klanten' bevatten de volledige mapping database"
                    )
                    mapping_file_path = os.path.join(GENERATED_FILES_DIR, selected_mapping)
                    mapping_filename = selected_mapping
                else:
                    st.warning("Geen 'alle_klanten' mapping bestanden gevonden")
            else:
                st.warning(f"Geen mapping bestanden gevonden voor {internal_type}")

        else:
            uploaded_mapping = st.file_uploader(
                "Upload mapping bestand (CSV)",
                type=['csv'],
                key="mapping_upload"
            )
            if uploaded_mapping:
                mapping_file_content = uploaded_mapping.getvalue()
                mapping_filename = uploaded_mapping.name

        # Preview mapping file
        if mapping_file_path:
            with st.expander("Preview mapping bestand"):
                preview = load_file_preview(mapping_file_path)
                if preview is not None:
                    st.dataframe(preview, use_container_width=True)
                    st.caption(f"Kolommen: {', '.join(preview.columns)}")

    # Right column - Target file selection
    with col2:
        st.subheader("2. Doel Bestand (Te verrijken)")
        st.caption("Dit is het bestand van de nieuwe klant dat gemapt moet worden")

        target_source = st.radio(
            "Doel bestand bron:",
            source_options,
            key="target_source",
            horizontal=True
        )

        target_file_path = None
        target_file_content = None
        target_filename = None

        if target_source == "Selecteer bestaand bestand":
            available_targets = get_available_target_files(internal_type)

            if available_targets:
                selected_target = st.selectbox(
                    "Kies doel bestand:",
                    available_targets,
                    help="Selecteer het klantbestand dat gemapt moet worden"
                )
                target_file_path = os.path.join(GENERATED_FILES_DIR, selected_target)
                target_filename = selected_target
            else:
                st.warning(f"Geen doel bestanden gevonden voor {internal_type}")

        else:
            uploaded_target = st.file_uploader(
                "Upload doel bestand (CSV)",
                type=['csv'],
                key="target_upload"
            )
            if uploaded_target:
                target_file_content = uploaded_target.getvalue()
                target_filename = uploaded_target.name

        # Preview target file
        if target_file_path:
            with st.expander("Preview doel bestand"):
                preview = load_file_preview(target_file_path)
                if preview is not None:
                    st.dataframe(preview, use_container_width=True)
                    st.caption(f"Kolommen: {', '.join(preview.columns)}")

    st.divider()

    # Run mapping button
    can_run = (mapping_file_path or mapping_file_content) and (target_file_path or target_file_content)

    if can_run:
        if st.button("Start Mapping", type="primary", use_container_width=True):
            run_mapping(
                learning_store,
                internal_type,
                mapping_file_path,
                mapping_file_content,
                mapping_filename,
                target_file_path,
                target_file_content,
                target_filename,
                min_fill_rate,
                use_learning
            )
    else:
        st.info("Selecteer zowel een mapping bestand als een doel bestand om te beginnen")


def run_mapping(
    learning_store: LearningStore,
    mapping_type: str,
    mapping_path: Optional[str],
    mapping_content: Optional[bytes],
    mapping_filename: str,
    target_path: Optional[str],
    target_content: Optional[bytes],
    target_filename: str,
    min_fill_rate: float,
    use_learning: bool
):
    """Run the mapping process with learning integration."""
    from src.normalization import normalize_taken, normalize_rubriek
    from src.utils import validate_columns

    progress_bar = st.progress(0, text="Initialiseren...")

    try:
        # Step 1: Initialize mapper
        if mapping_type == "Taken":
            mapper = TakenMapper(min_fill_rate=min_fill_rate)
        else:
            mapper = WVBalansMapper(min_fill_rate=min_fill_rate)

        progress_bar.progress(10, text="Mapping bestand laden...")

        # Step 2: Load mapping file
        if mapping_path:
            mapping_stats = mapper.load_mapping(mapping_path)
        else:
            mapping_stats = mapper.load_mapping(mapping_content, is_content=True, filename=mapping_filename)

        # Show learned mappings count
        learned_count = len(learning_store.get_all_learned_mappings(mapping_type))
        if use_learning and learned_count > 0:
            st.info(f"Geleerde mappings: {learned_count} extra regels uit correcties")

        st.success(f"Mapping bestand geladen: {mapping_stats['valid_rows']:,} geldige regels, {mapping_stats['unique_keys']:,} unieke keys")

        progress_bar.progress(40, text="Doel bestand verwerken...")

        # Step 3: Read target file
        if target_path:
            df, delimiter = read_csv_robust(target_path)
        else:
            df, delimiter = read_csv_robust(target_content, is_content=True)

        # Validate columns based on type
        if mapping_type == "Taken":
            col_map = validate_columns(df, ['Taak', 'Type'], "Target file")
            has_client = 'Klantnummer' in df.columns
            df['Taakgroepcode'] = ""
            df['Taakgroep'] = ""
        else:
            col_map = validate_columns(df, ['Rubriek'], "Target file")
            has_client = False
            df['CoA_code'] = ""
            df['Niveau1'] = ""
            df['Niveau2'] = ""

        # Track results
        unmatched_rows = []
        detailed_results = []
        match_methods = {}
        learned_matches = 0

        total_rows = len(df)
        for idx, row in df.iterrows():
            if idx % 100 == 0:
                progress_bar.progress(40 + int(40 * idx / total_rows), text=f"Verwerken rij {idx+1}/{total_rows}...")

            if mapping_type == "Taken":
                original_input = str(row[col_map['Taak']]).strip() if pd.notna(row[col_map['Taak']]) else ""
                taak_type = str(row[col_map['Type']]).strip() if pd.notna(row[col_map['Type']]) else ""
                normalized = normalize_taken(original_input, taak_type)
                extra_context = {'type': taak_type}
                client_id = str(row['Klantnummer']).strip() if has_client and pd.notna(row.get('Klantnummer')) else None
            else:
                original_input = str(row[col_map['Rubriek']]).strip() if pd.notna(row[col_map['Rubriek']]) else ""
                normalized = normalize_rubriek(original_input)
                extra_context = {}
                taak_type = None
                client_id = None

            if not original_input:
                continue

            # First check learned mappings
            result = None
            method = 'unmatched'
            confidence = 0.0

            if use_learning:
                learned = learning_store.get_learned_mapping(mapping_type, normalized, extra_context)
                if learned:
                    result = learned
                    method = 'learned'
                    confidence = 1.0
                    learned_matches += 1

            # Fall back to base matcher
            if result is None:
                if mapping_type == "Taken":
                    result, method = mapper.matcher.match(normalized, taak_type, client_id)
                else:
                    result, method = mapper.matcher.match(normalized)

                # Calculate confidence
                confidence_map = {
                    'A_exact': 1.0, 'exact': 1.0,
                    'B_anchor': 0.95, 'anchor_fixed': 0.95, 'anchor_niveau': 0.90,
                    'C_prefix': 0.85, 'prefix': 0.85,
                    'D_token_set': 0.80, 'fuzzy': 0.80,
                    'E_token_sort': 0.75,
                    'G_majority': 0.70,
                    'H_client_top': 0.60, 'H_type_top': 0.50,
                    'unmatched': 0.0,
                }
                confidence = confidence_map.get(method, 0.5)

            # Update dataframe
            if result:
                if mapping_type == "Taken":
                    df.at[idx, 'Taakgroepcode'] = result[0]
                    df.at[idx, 'Taakgroep'] = result[1]
                else:
                    df.at[idx, 'CoA_code'] = result[0]
                    df.at[idx, 'Niveau1'] = result[1]
                    df.at[idx, 'Niveau2'] = result[2]
            else:
                if mapping_type == "Taken":
                    unmatched_rows.append({
                        'UniekeID': idx + 1,
                        'Klantnummer': client_id or '',
                        'Taak': original_input,
                        'Type': taak_type,
                        'normalisatie': normalized,
                    })
                else:
                    unmatched_rows.append({
                        'UniekeID': idx + 1,
                        'Rubriek': original_input,
                        'normalisatie': normalized,
                    })

            # Track method counts
            match_methods[method] = match_methods.get(method, 0) + 1

            # Store detailed result for review
            detailed_results.append({
                'row_idx': idx,
                'original_input': original_input,
                'normalized': normalized,
                'result': result,
                'method': method,
                'confidence': confidence,
                'extra_context': extra_context,
            })

            # Log prediction (for learning)
            learning_store.log_prediction(
                mapping_type,
                original_input,
                normalized,
                result,
                method,
                confidence,
                extra_context
            )

        progress_bar.progress(85, text="Statistieken berekenen...")

        # Create unmatched DataFrame
        if mapping_type == "Taken":
            unmatched_df = pd.DataFrame(unmatched_rows, columns=['UniekeID', 'Klantnummer', 'Taak', 'Type', 'normalisatie'])
        else:
            unmatched_df = pd.DataFrame(unmatched_rows, columns=['UniekeID', 'Rubriek', 'normalisatie'])

        # Calculate stats
        filled_count = total_rows - len(unmatched_rows)
        fill_rate = filled_count / total_rows if total_rows > 0 else 0

        run_stats = {
            'total_rows': total_rows,
            'filled_rows': filled_count,
            'unmatched_rows': len(unmatched_rows),
            'fill_rate': fill_rate,
            'fill_rate_pct': f"{fill_rate * 100:.1f}%",
            'match_methods': match_methods,
            'meets_threshold': fill_rate >= min_fill_rate,
            'learned_matches': learned_matches,
        }

        progress_bar.progress(95, text="Resultaten weergeven...")

        # Store results in session state for review page
        st.session_state['last_results'] = {
            'mapping_type': mapping_type,
            'enriched_df': df,
            'unmatched_df': unmatched_df,
            'detailed_results': detailed_results,
            'target_filename': target_filename,
        }

        # Display results
        display_results(
            mapper, learning_store, mapping_type, df, unmatched_df,
            run_stats, detailed_results, target_filename, min_fill_rate
        )

        progress_bar.progress(100, text="Klaar!")

    except Exception as e:
        st.error(f"Fout tijdens mapping: {str(e)}")
        import traceback
        with st.expander("Technische details"):
            st.code(traceback.format_exc())


def display_results(
    mapper,
    learning_store: LearningStore,
    mapping_type: str,
    enriched_df: pd.DataFrame,
    unmatched_df: pd.DataFrame,
    run_stats: dict,
    detailed_results: list,
    target_filename: str,
    min_fill_rate: float
):
    """Display mapping results with learning integration."""

    st.divider()
    st.header("Resultaten")

    # Summary metrics
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Totaal rijen", f"{run_stats['total_rows']:,}")

    with col2:
        st.metric("Gevuld", f"{run_stats['filled_rows']:,}")

    with col3:
        st.metric("Niet gematched", f"{run_stats['unmatched_rows']:,}")

    with col4:
        fill_rate_pct = run_stats['fill_rate'] * 100
        delta = fill_rate_pct - (min_fill_rate * 100)
        st.metric(
            "Fill Rate",
            f"{fill_rate_pct:.1f}%",
            delta=f"{delta:+.1f}% vs target",
            delta_color="normal" if run_stats['meets_threshold'] else "inverse"
        )

    with col5:
        st.metric(
            "Geleerd",
            f"{run_stats.get('learned_matches', 0)}",
            help="Matches uit geleerde correcties"
        )

    # Status message
    if run_stats['meets_threshold']:
        st.success(f"Fill rate van {fill_rate_pct:.1f}% voldoet aan de target van {min_fill_rate*100:.0f}%")
    else:
        st.warning(f"Fill rate van {fill_rate_pct:.1f}% voldoet NIET aan de target van {min_fill_rate*100:.0f}%")

    # Match methods breakdown
    with st.expander("Match Methodes Breakdown", expanded=True):
        methods_df = pd.DataFrame([
            {"Methode": method, "Aantal": count}
            for method, count in sorted(run_stats['match_methods'].items(), key=lambda x: -x[1])
        ])
        st.dataframe(methods_df, use_container_width=True, hide_index=True)

    # Preview enriched data
    with st.expander("Preview verrijkte data", expanded=True):
        st.dataframe(enriched_df.head(20), use_container_width=True)

    # Low confidence matches for review
    low_confidence = [r for r in detailed_results if 0 < r['confidence'] < 0.75]
    if low_confidence:
        with st.expander(f"Te reviewen: {len(low_confidence)} lage confidence matches", expanded=False):
            st.caption("Deze matches hebben een lage confidence score en kunnen baat hebben bij handmatige review")

            for i, result in enumerate(low_confidence[:20]):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{result['original_input']}**")
                    st.caption(f"→ {result['result']}")
                with col2:
                    st.write(f"Methode: `{result['method']}`")
                with col3:
                    conf_class = get_confidence_class(result['confidence'])
                    st.markdown(f"<span class='{conf_class}'>{result['confidence']*100:.0f}%</span>", unsafe_allow_html=True)

    # Unmatched rows
    if not unmatched_df.empty:
        with st.expander(f"Niet-gematchte rijen ({len(unmatched_df)})", expanded=False):
            st.dataframe(unmatched_df, use_container_width=True)

    st.divider()

    # Download section
    st.header("Download")

    # Prepare download data
    output_dir = OUTPUT_DIRS[mapping_type]
    base_name = extract_base_name(target_filename)

    # Get Amsterdam date
    tz = pytz.timezone('Europe/Amsterdam')
    today = datetime.now(tz).strftime('%Y-%m-%d')

    enriched_filename = f"{base_name}_{today}.csv"
    unmatched_filename = f"{base_name}_unmatched_{today}.csv"

    col1, col2, col3 = st.columns(3)

    with col1:
        # Convert to CSV for download
        enriched_csv = enriched_df.to_csv(sep=';', index=False).encode('utf-8-sig')
        st.download_button(
            label="Download verrijkt bestand",
            data=enriched_csv,
            file_name=enriched_filename,
            mime="text/csv",
            type="primary"
        )

    with col2:
        if not unmatched_df.empty:
            unmatched_csv = unmatched_df.to_csv(sep=';', index=False).encode('utf-8-sig')
            st.download_button(
                label="Download ongematchte rijen",
                data=unmatched_csv,
                file_name=unmatched_filename,
                mime="text/csv"
            )

    with col3:
        # Full report
        report = mapper.generate_report()
        st.download_button(
            label="Download rapport (TXT)",
            data=report.encode('utf-8'),
            file_name=f"{base_name}_report_{today}.txt",
            mime="text/plain"
        )

    # Save to disk option (only when local output dir is accessible)
    if os.path.isdir(os.path.dirname(output_dir)):
        st.divider()
        st.subheader("Opslaan naar schijf")

        save_col1, save_col2 = st.columns([3, 1])

        with save_col1:
            st.info(f"Output directory: `{output_dir}`")

        with save_col2:
            if st.button("Opslaan naar output directory"):
                try:
                    os.makedirs(output_dir, exist_ok=True)

                    enriched_path = os.path.join(output_dir, enriched_filename)
                    unmatched_path = os.path.join(output_dir, unmatched_filename)

                    # Write files
                    enriched_df.to_csv(enriched_path, sep=';', index=False, encoding='utf-8-sig')
                    if not unmatched_df.empty:
                        unmatched_df.to_csv(unmatched_path, sep=';', index=False, encoding='utf-8-sig')

                    st.success(f"Bestanden opgeslagen!")
                    st.write(f"- `{enriched_path}`")
                    if not unmatched_df.empty:
                        st.write(f"- `{unmatched_path}`")

                except Exception as e:
                    st.error(f"Fout bij opslaan: {e}")


def show_review_page(learning_store: LearningStore):
    """Show the review and corrections page."""
    st.header("Review & Correcties")
    st.caption("Bekijk en corrigeer mappings om het systeem te trainen")

    if 'last_results' not in st.session_state:
        st.info("Voer eerst een mapping uit om resultaten te kunnen reviewen")
        return

    results = st.session_state['last_results']
    mapping_type = results['mapping_type']
    detailed_results = results['detailed_results']

    # Filter options
    col1, col2 = st.columns(2)
    with col1:
        filter_type = st.selectbox(
            "Filter op:",
            ["Alle resultaten", "Lage confidence (<75%)", "Niet gematched", "Geleerd"]
        )
    with col2:
        sort_by = st.selectbox(
            "Sorteer op:",
            ["Confidence (laag-hoog)", "Confidence (hoog-laag)", "Originele volgorde"]
        )

    # Apply filters
    filtered = detailed_results.copy()
    if filter_type == "Lage confidence (<75%)":
        filtered = [r for r in filtered if 0 < r['confidence'] < 0.75]
    elif filter_type == "Niet gematched":
        filtered = [r for r in filtered if r['result'] is None]
    elif filter_type == "Geleerd":
        filtered = [r for r in filtered if r['method'] == 'learned']

    # Apply sorting
    if sort_by == "Confidence (laag-hoog)":
        filtered.sort(key=lambda x: x['confidence'])
    elif sort_by == "Confidence (hoog-laag)":
        filtered.sort(key=lambda x: -x['confidence'])

    st.write(f"Toon {len(filtered)} van {len(detailed_results)} resultaten")

    # Display results with correction capability
    for i, result in enumerate(filtered[:50]):  # Limit to 50 for performance
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 1, 2])

            with col1:
                st.write(f"**{result['original_input']}**")
                st.caption(f"Genormaliseerd: `{result['normalized']}`")

            with col2:
                if result['result']:
                    st.write(f"→ {result['result']}")
                else:
                    st.write("→ *Geen match*")

            with col3:
                conf_class = get_confidence_class(result['confidence'])
                method_badge = "🧠" if result['method'] == 'learned' else ""
                st.markdown(f"{method_badge} <span class='{conf_class}'>{result['confidence']*100:.0f}%</span>", unsafe_allow_html=True)
                st.caption(result['method'])

            with col4:
                if st.button("Corrigeer", key=f"correct_{i}"):
                    st.session_state[f'correcting_{i}'] = True

            # Show correction form if clicked
            if st.session_state.get(f'correcting_{i}', False):
                with st.form(key=f"correction_form_{i}"):
                    st.write("Voer de juiste mapping in:")

                    if mapping_type == "Taken":
                        new_code = st.text_input("Taakgroepcode", key=f"code_{i}")
                        new_group = st.text_input("Taakgroep", key=f"group_{i}")

                        if st.form_submit_button("Opslaan"):
                            if new_code and new_group:
                                learning_store.log_correction(
                                    mapping_type,
                                    result['original_input'],
                                    result['normalized'],
                                    result['result'],
                                    (new_code, new_group),
                                    result['extra_context']
                                )
                                st.success("Correctie opgeslagen!")
                                st.session_state[f'correcting_{i}'] = False
                                st.rerun()
                    else:
                        new_code = st.text_input("CoA_code", key=f"code_{i}")
                        new_n1 = st.text_input("Niveau1", key=f"n1_{i}")
                        new_n2 = st.text_input("Niveau2", key=f"n2_{i}")

                        if st.form_submit_button("Opslaan"):
                            if new_code and new_n1 and new_n2:
                                learning_store.log_correction(
                                    mapping_type,
                                    result['original_input'],
                                    result['normalized'],
                                    result['result'],
                                    (new_code, new_n1, new_n2),
                                    result['extra_context']
                                )
                                st.success("Correctie opgeslagen!")
                                st.session_state[f'correcting_{i}'] = False
                                st.rerun()

        st.divider()


def show_learning_dashboard(learning_store: LearningStore):
    """Show the learning analytics dashboard."""
    st.header("Learning Dashboard")
    st.caption("Bekijk hoe het systeem leert van correcties")

    stats = learning_store.get_statistics()

    # Overview metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Totaal Voorspellingen", f"{stats['total_predictions']:,}")

    with col2:
        st.metric("Totaal Correcties", f"{stats['total_corrections']:,}")

    with col3:
        st.metric("Geleerde Mappings", f"{stats['total_learned_mappings']:,}")

    with col4:
        if stats.get('overall_accuracy') is not None:
            st.metric("Nauwkeurigheid", f"{stats['overall_accuracy']*100:.1f}%")
        else:
            st.metric("Nauwkeurigheid", "N/A")

    st.divider()

    # Learned mappings
    st.subheader("Geleerde Mappings")

    learned = learning_store.get_all_learned_mappings()
    if learned:
        learned_df = pd.DataFrame(learned)
        st.dataframe(learned_df, use_container_width=True, hide_index=True)

        # Export button
        tz = pytz.timezone('Europe/Amsterdam')
        today = datetime.now(tz).strftime('%Y-%m-%d')

        export_path = os.path.join(LEARNING_DIR, f'learned_mappings_export_{today}.csv')

        if st.button("Exporteer geleerde mappings"):
            export_learned_mappings_to_csv(learning_store, export_path)
            st.success(f"Geexporteerd naar: `{export_path}`")

    else:
        st.info("Nog geen geleerde mappings. Voer correcties uit om het systeem te trainen.")

    st.divider()

    # Corrections over time
    st.subheader("Correcties over tijd")

    if stats['corrections_over_time']:
        corrections_df = pd.DataFrame(stats['corrections_over_time'])
        st.bar_chart(corrections_df.set_index('date'))
    else:
        st.info("Nog geen correcties gelogd.")

    # Top corrected inputs
    st.subheader("Meest gecorrigeerde invoer")

    if stats['top_corrected_inputs']:
        top_df = pd.DataFrame(stats['top_corrected_inputs'][:10])
        st.dataframe(top_df, use_container_width=True, hide_index=True)
    else:
        st.info("Nog geen correcties gelogd.")

    # Accuracy by type
    if stats['accuracy_by_type']:
        st.subheader("Statistieken per type")

        for mapping_type, type_stats in stats['accuracy_by_type'].items():
            with st.expander(f"{mapping_type} ({type_stats['total']} voorspellingen)"):
                methods_df = pd.DataFrame([
                    {"Methode": m, "Aantal": c}
                    for m, c in sorted(type_stats['methods'].items(), key=lambda x: -x[1])
                ])
                st.dataframe(methods_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
