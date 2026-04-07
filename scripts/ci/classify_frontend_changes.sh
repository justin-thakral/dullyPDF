#!/usr/bin/env bash
set -euo pipefail

changed_files="${CHANGED_FRONTEND_FILES:-}"

run_runtime_tests=false
run_content_tests=false
run_build=false

set_output() {
  local key="$1"
  local value="$2"
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf '%s=%s\n' "$key" "$value" >>"$GITHUB_OUTPUT"
  else
    printf '%s=%s\n' "$key" "$value"
  fi
}

is_content_source() {
  local path="$1"
  case "$path" in
    frontend/src/components/pages/BlogIndexPage.*|\
    frontend/src/components/pages/BlogPostPage.*|\
    frontend/src/components/pages/FeaturePlanPage.*|\
    frontend/src/components/pages/Homepage.*|\
    frontend/src/components/pages/IntentHubPage.*|\
    frontend/src/components/pages/IntentLandingPage.*|\
    frontend/src/components/pages/IntentPageShell.*|\
    frontend/src/components/pages/LegalPage.*|\
    frontend/src/components/pages/PublicNotFoundPage.*|\
    frontend/src/components/pages/SeoLayoutPreviewPage.*|\
    frontend/src/components/pages/UsageDocsNotFoundPage.*|\
    frontend/src/components/pages/UsageDocsPage.*|\
    frontend/src/components/pages/usageDocsContent.*|\
    frontend/src/config/blogPosts.ts|\
    frontend/src/config/blogSeo.ts|\
    frontend/src/config/featurePlanPages.ts|\
    frontend/src/config/intentPages.ts|\
    frontend/src/config/publicRouteSeoData.mjs|\
    frontend/src/config/routeSeo.ts|\
    frontend/src/config/seoHelpers.ts|\
    scripts/generate-static-html.mjs|\
    scripts/seo-route-data.mjs)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_content_test() {
  local path="$1"
  case "$path" in
    frontend/test/unit/components/pages/test_blog_index_page.test.tsx|\
    frontend/test/unit/components/pages/test_blog_post_page.test.tsx|\
    frontend/test/unit/components/pages/test_feature_plan_page.test.tsx|\
    frontend/test/unit/components/pages/test_homepage.test.tsx|\
    frontend/test/unit/components/pages/test_intent_hub_page.test.tsx|\
    frontend/test/unit/components/pages/test_intent_landing_page.test.tsx|\
    frontend/test/unit/components/pages/test_legal_page.test.tsx|\
    frontend/test/unit/components/pages/test_public_not_found_page.test.tsx|\
    frontend/test/unit/components/pages/test_usage_docs_content.test.ts|\
    frontend/test/unit/components/pages/test_usage_docs_not_found_page.test.tsx|\
    frontend/test/unit/components/pages/test_usage_docs_page.test.tsx|\
    frontend/test/unit/config/test_feature_plan_pages.test.ts|\
    frontend/test/unit/config/test_intent_pages.test.ts|\
    frontend/test/unit/config/test_route_seo.test.ts|\
    frontend/test/unit/scripts/test_generate_static_html.test.ts|\
    frontend/test/unit/legacy/*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_runtime_test() {
  local path="$1"
  case "$path" in
    frontend/test/unit/*|frontend/test/setup.ts)
      is_content_test "$path" && return 1
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

needs_build_for_path() {
  local path="$1"
  case "$path" in
    frontend/src/*|frontend/public/*|frontend/package.json|frontend/package-lock.json|frontend/vite.config.*|package.json|scripts/use-frontend-env.sh)
      return 0
      ;;
    *)
      is_content_source "$path"
      ;;
  esac
}

is_runtime_path() {
  local path="$1"
  case "$path" in
    frontend/README.md|frontend/docs/*|frontend/test/docs/*)
      return 1
      ;;
    frontend/src/*|frontend/package.json|frontend/package-lock.json|frontend/vite.config.*|package.json|scripts/use-frontend-env.sh)
      is_content_source "$path" && return 1
      return 0
      ;;
    *)
      is_runtime_test "$path"
      ;;
  esac
}

while IFS= read -r path; do
  [[ -z "$path" ]] && continue

  if is_runtime_path "$path"; then
    run_runtime_tests=true
  fi

  if is_content_source "$path" || is_content_test "$path"; then
    run_content_tests=true
  fi

  if needs_build_for_path "$path"; then
    run_build=true
  fi
done < <(printf '%s\n' "$changed_files" | tr ' ' '\n' | sed '/^$/d')

set_output "run_runtime_tests" "$run_runtime_tests"
set_output "run_content_tests" "$run_content_tests"
set_output "run_build" "$run_build"
