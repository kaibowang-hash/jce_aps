### Injection APS

Injection-focused APS (Advanced Planning and Scheduling) app for ERPNext.

This app is designed to stay isolated from standard ERPNext and the existing
custom apps in this bench:

- No global `app_include_js`
- No overrides of standard ERPNext manufacturing controllers
- Standard custom fields are created and removed only by this app's
  install/migrate/uninstall hooks
- Existing execution objects stay in `zelin_pp` / `light_mes`
- Uninstall is blocked while APS business data or standard-document APS
  references still exist

## Documentation

- Chinese user guide: [`docs/aps_user_guide_zh.md`](docs/aps_user_guide_zh.md)
- Module Chinese translations: [`injection_aps/translations/zh.csv`](injection_aps/translations/zh.csv)
