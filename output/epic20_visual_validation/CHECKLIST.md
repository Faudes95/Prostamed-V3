# EPIC 20 Visual Validation Checklist

Generated: 2026-05-13T18:06:58
Reference: NCCN Prostate Cancer v2026

## Summary

- Total exemplars: 18
- Classifications matched: 18/18

## Per-exemplar review

| # | Exemplar | Expected state | Actual state | Match | HTML |
|---|----------|----------------|--------------|-------|------|
| 1 | `exemplar_01_very_low_risk` | `very_low_risk_localized` | `very_low_risk_localized` | ✅ | [exemplar_01_very_low_risk.html](./exemplar_01_very_low_risk.html) |
| 2 | `exemplar_02_low_risk` | `low_risk_localized` | `low_risk_localized` | ✅ | [exemplar_02_low_risk.html](./exemplar_02_low_risk.html) |
| 3 | `exemplar_03_favorable_intermediate` | `favorable_intermediate_risk_localized` | `favorable_intermediate_risk_localized` | ✅ | [exemplar_03_favorable_intermediate.html](./exemplar_03_favorable_intermediate.html) |
| 4 | `exemplar_04_unfavorable_intermediate` | `unfavorable_intermediate_risk_localized` | `unfavorable_intermediate_risk_localized` | ✅ | [exemplar_04_unfavorable_intermediate.html](./exemplar_04_unfavorable_intermediate.html) |
| 5 | `exemplar_05_high_risk` | `high_risk_localized` | `high_risk_localized` | ✅ | [exemplar_05_high_risk.html](./exemplar_05_high_risk.html) |
| 6 | `exemplar_06_very_high_risk` | `very_high_risk_localized` | `very_high_risk_localized` | ✅ | [exemplar_06_very_high_risk.html](./exemplar_06_very_high_risk.html) |
| 7 | `exemplar_07_post_rt_bcr` | `post_rt_bcr` | `post_rt_bcr` | ✅ | [exemplar_07_post_rt_bcr.html](./exemplar_07_post_rt_bcr.html) |
| 8 | `exemplar_08_mcspc_latitude` | `mcspc_latitude_high_risk` | `mcspc_latitude_high_risk` | ✅ | [exemplar_08_mcspc_latitude.html](./exemplar_08_mcspc_latitude.html) |
| 9 | `exemplar_09_mcspc_visceral_only` | `mcspc_visceral_only_m1c` | `mcspc_visceral_only_m1c` | ✅ | [exemplar_09_mcspc_visceral_only.html](./exemplar_09_mcspc_visceral_only.html) |
| 10 | `exemplar_10_mcspc_psma_only` | `mcspc_psma_only_metastatic` | `mcspc_psma_only_metastatic` | ✅ | [exemplar_10_mcspc_psma_only.html](./exemplar_10_mcspc_psma_only.html) |
| 11 | `exemplar_11_mcrpc_arsi_naive` | `mcrpc_arsi_naive` | `mcrpc_arsi_naive` | ✅ | [exemplar_11_mcrpc_arsi_naive.html](./exemplar_11_mcrpc_arsi_naive.html) |
| 12 | `exemplar_12_mcrpc_post_arsi` | `mcrpc_post_arsi` | `mcrpc_post_arsi` | ✅ | [exemplar_12_mcrpc_post_arsi.html](./exemplar_12_mcrpc_post_arsi.html) |
| 13 | `exemplar_13_mcrpc_hrr_parp_naive` | `mcrpc_hrr_positive_parp_naive` | `mcrpc_hrr_positive_parp_naive` | ✅ | [exemplar_13_mcrpc_hrr_parp_naive.html](./exemplar_13_mcrpc_hrr_parp_naive.html) |
| 14 | `exemplar_14_mcrpc_psma_lu177` | `mcrpc_psma_eligible_lu177` | `mcrpc_psma_eligible_lu177` | ✅ | [exemplar_14_mcrpc_psma_lu177.html](./exemplar_14_mcrpc_psma_lu177.html) |
| 15 | `exemplar_15_mcrpc_msi_h` | `mcrpc_msi_h_dmmr` | `mcrpc_msi_h_dmmr` | ✅ | [exemplar_15_mcrpc_msi_h.html](./exemplar_15_mcrpc_msi_h.html) |
| 16 | `exemplar_16_nepc` | `nepc_differentiation` | `nepc_differentiation` | ✅ | [exemplar_16_nepc.html](./exemplar_16_nepc.html) |
| 17 | `exemplar_17_hereditary_umbrella` | `hereditary_germline_pathway_umbrella` | `hereditary_germline_pathway_umbrella` | ✅ | [exemplar_17_hereditary_umbrella.html](./exemplar_17_hereditary_umbrella.html) |
| 18 | `exemplar_18_oligo_progressive` | `oligo_progressive_on_therapy` | `oligo_progressive_on_therapy` | ✅ | [exemplar_18_oligo_progressive.html](./exemplar_18_oligo_progressive.html) |

## Clinical reviewer instructions

Para cada exemplar:

1. Abrir el HTML correspondiente en navegador
2. Comparar `Expected` vs `Actual classification`
3. Verificar el checklist clínico de cada página
4. Marcar fail si:
   - State name no coincide (clinical regression)
   - Therapeutic alternative no es clinicamente correcto
   - Rationale tiene errores de lógica clínica
   - Evidence reference es incorrecto o falta
5. Reportar fails al equipo → fix rule → re-run harness → re-review

## Auto-screenshot (opcional, con Playwright)

Si querés capturar PNGs de cada HTML:

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    for html_file in Path('output/epic20_visual_validation').glob('*.html'):
        page = browser.new_page()
        page.goto(f'file://{html_file.absolute()}')
        page.screenshot(path=html_file.with_suffix('.png'))
    browser.close()
```