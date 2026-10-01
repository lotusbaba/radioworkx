# Implemented adversarial test scenarios

Inventory: **88 contract/router cases**, plus **12 account scenario cases** and **54 social cases**,
for **154 cases listed here** (updated 2026-09-29). The original 88 comprise 37 action-contract
cases and 51 routing/decision cases. Each parameterized case
is listed separately; a case may contain several assertions.

The original 88 are unit tests for the implemented contracts and decision router. They do
not run browsers, call models, or test live RadioWorkx workflows. The last execution
passed all 88 cases. The eight playlist cases previously reproduced known gaps as expected failures.
The stale-collection regression is now covered by the social feature’s
account/request-generation guard. See the consolidated social run below. Broader scenarios remain in
[adversarial-scenarios.md](adversarial-scenarios.md); implementation status is in
[architecture.md](architecture.md).

```sh
# List the exact test IDs
.venv/bin/python -m pytest tests/adversary --confcutdir=tests/adversary --collect-only -q

# Run all 88 cases
.venv/bin/python -m pytest tests/adversary --confcutdir=tests/adversary -q
```

Each table uses the linked source file and function named above it. The parameter
column supplies the exact pytest suffix (or `—` for an unparameterized test), so the
full node ID is `tests/adversary/<file>.py::<function>[<parameter>]`.

## Action contracts — 37 cases

Source: [test_actions.py](../tests/adversary/test_actions.py).

### `test_actions_preserve_exact_parameters_and_ordered_locators`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 1 | `action0` | Navigate to `/artists` preserves the relative URL through JSON serialization. |
| 2 | `action1` | Click preserves its target and ordered locator alternatives. |
| 3 | `action2` | Fill preserves whitespace, newline, Unicode and emoji exactly. |
| 4 | `action3` | Fill preserves an intentionally empty string. |
| 5 | `action4` | Select preserves an empty-string option value. |
| 6 | `action5` | Hover preserves its target and ordered locator alternatives. |
| 7 | `action6` | Scroll preserves a negative vertical delta of −300. |
| 8 | `action7` | Back round-trips as a concrete action. |
| 9 | `action8` | Forward round-trips as a concrete action. |
| 10 | `action9` | Reload round-trips as a concrete action. |
| 11 | `action10` | Wait preserves a 250 ms duration. |
| 12 | `action11` | Key press preserves the target and Enter key. |
| 13 | `action12` | Submit preserves its target and ordered locator alternatives. |
| 14 | `action13` | Done preserves the completion reason. |

### `test_invalid_actions_fail_at_the_contract_boundary`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 15 | `action0` | Reject an unsupported `evaluate` action carrying JavaScript. |
| 16 | `action1` | Reject click without a target. |
| 17 | `action2` | Reject fill without a value. |
| 18 | `action3` | Reject fill with a null value. |
| 19 | `action4` | Reject fill with a numeric value. |
| 20 | `action5` | Reject select with no option values. |
| 21 | `action6` | Reject scroll with zero movement on both axes. |
| 22 | `action7` | Reject a NaN scroll delta. |
| 23 | `action8` | Reject a Boolean scroll delta. |
| 24 | `action9` | Reject navigation with an empty URL. |
| 25 | `action10` | Reject a negative wait duration. |
| 26 | `action11` | Reject a wait longer than its action timeout. |
| 27 | `action12` | Reject an extraneous target on a back action. |
| 28 | `action13` | Reject an extraneous script on a back action. |
| 29 | `action14` | Reject unsupported schema version 2. |
| 30 | `action15` | Reject a Boolean schema version. |
| 31 | `action16` | Reject a floating-point schema version. |
| 32 | `action17` | Reject a zero action timeout. |
| 33 | `action18` | Reject done with an empty reason. |
| 34 | `action19` | Reject a target with no locator alternatives. |
| 35 | `action20` | Reject a role locator without an accessible name. |
| 36 | `action21` | Reject a whitespace-only CSS locator. |

### `test_domain_imports_do_not_load_browser_model_or_radio_runtime`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 37 | `—` | Import contracts and router without loading Playwright, Browser Use, Laya, Torch or the radio app. |

## Routing and decisions — 51 cases

Source: [test_router.py](../tests/adversary/test_router.py).

### `test_complete_empty_string_action_routes_to_laya_with_request_identity`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 38 | `—` | Route a fully covered empty-string fill to Laya; retain request/session/observation/step identity and round-trip the route result. |

### `test_uncovered_decisions_require_llm`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 39 | `changes0-no_candidates` | Route an empty candidate set to the LLM. |
| 40 | `changes1-too_many_candidates` | Route 11 candidates to the LLM when the limit is 10. |
| 41 | `changes2-unknown_widget_required` | Route to the LLM when the current decision requires an unknown widget. |
| 42 | `changes3-incomplete_coverage` | Route to the LLM when candidate coverage is not explicitly complete. |
| 43 | `changes4-operation_not_covered` | Route to the LLM when an operation is outside the strategy allowlist. |

### `test_candidate_limit_is_inclusive_and_configurable`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 44 | `—` | Accept 10 candidates at limit 10; route the same set to the LLM when the configured limit is 9. |

### `test_unavailable_laya_does_not_silently_fallback`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 45 | `models0-limits0-laya_unavailable` | Block when the selected Laya backend is unavailable, even if the LLM is available. |
| 46 | `models1-limits1-laya_budget_exhausted` | Block when Laya call budget is exhausted, without falling back to the LLM. |

### `test_unavailable_or_exhausted_llm_blocks_without_using_laya`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 47 | `models0-limits0-llm_unavailable` | Block an uncovered decision when the LLM is unavailable, without substituting Laya. |
| 48 | `models1-limits1-hosted_llm_disabled` | Block hosted LLM routing when hosted access is disabled. |
| 49 | `models2-limits2-llm_call_budget_exhausted` | Block LLM routing when its call budget is exhausted. |
| 50 | `models3-limits3-llm_cost_budget_exhausted` | Block LLM routing when remaining cost budget is below the per-call reservation. |

### `test_hosted_backend_requires_explicit_opt_in_and_sufficient_budget`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 51 | `—` | Allow hosted LLM routing with explicit opt-in and cost budget exactly equal to the reservation. |

### `test_free_local_model_requires_calls_but_no_cost_budget`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 52 | `—` | Allow a free local LLM with call budget and zero cost budget/reservation. |

### `test_expired_session_blocks_both_paths`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 53 | `limits0` | Block both bounded and uncovered decisions when no session steps remain. |
| 54 | `limits1` | Block both bounded and uncovered decisions when no session time remains. |

### `test_unknown_strategy_is_configuration_error_not_llm_escalation`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 55 | `—` | Block an unconfigured strategy instead of escalating to the LLM. |

### `test_router_does_not_claim_policy_permission_or_mutate_budgets`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 56 | `—` | Keep budgets unchanged; routing a navigation candidate does not enforce origin policy or execute navigation. |

### `test_invalid_request_is_rejected_not_escalated`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 57 | `missing_value` | Reject a candidate fill missing its value before routing. |
| 58 | `missing_target` | Reject a candidate fill missing its target before routing. |
| 59 | `duplicate_id` | Reject duplicate candidate IDs. |
| 60 | `stale_target` | Reject a candidate target from a stale observation. |
| 61 | `unknown_target` | Reject a candidate target with an unknown element ID. |
| 62 | `different_locator` | Reject locator alternatives that differ from the observation snapshot. |
| 63 | `wrong_session` | Reject an agent/observation session mismatch. |

### `test_decision_resolves_only_original_candidate_and_round_trips`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 64 | `—` | Round-trip a request and resolve the selected original candidate, retaining its empty fill value. |

### `test_response_cannot_cross_session_or_snapshot`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 65 | `changes0` | Reject a decision with a different request ID. |
| 66 | `changes1` | Reject a decision with a different session ID. |
| 67 | `changes2` | Reject a decision with a different observation ID. |
| 68 | `changes3` | Reject a decision with a different step number. |
| 69 | `changes4` | Reject a decision selecting an invented candidate ID. |

### `test_invalid_router_configuration`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 70 | `changes0` | Reject a zero candidate limit. |
| 71 | `changes1` | Reject a candidate limit of 21 (above the supported maximum of 20). |
| 72 | `changes2` | Reject a Boolean candidate limit. |
| 73 | `changes3` | Reject a string candidate limit. |
| 74 | `changes4` | Reject duplicate strategy configurations. |

### `test_invalid_budget`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 75 | `changes0` | Reject NaN remaining time. |
| 76 | `changes1` | Reject infinite remaining time. |
| 77 | `changes2` | Reject negative remaining steps. |
| 78 | `changes3` | Reject negative remaining LLM cost budget. |
| 79 | `changes4` | Reject an infinite per-call cost reservation. |
| 80 | `changes5` | Reject a Boolean LLM call count. |

### `test_snapshot_cannot_be_mutated_after_routing`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 81 | `—` | Reject mutation of a validated candidate value; candidate and element collections are tuples. |

### `test_availability_requires_actual_booleans`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 82 | `laya_available` | Reject the string `false` for Laya availability. |
| 83 | `llm_available` | Reject the string `false` for LLM availability. |
| 84 | `llm_is_local` | Reject the string `false` for the local-LLM flag. |

### `test_empty_strategy_allowlist_never_routes_to_laya`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 85 | `—` | Treat an empty bounded-operation allowlist as uncovered, rather than selecting Laya. |

### `test_extra_unknown_widget_flag_does_not_silently_change_routing`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 86 | `—` | Reject the unsupported page-wide `has_unknown_widget` flag; only the decision-specific flag is accepted. |

### `test_duplicate_and_foreign_observed_elements_rejected`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 87 | `—` | Reject duplicate observed element IDs and elements bound to another observation. |

### `test_demo_reports_three_paths_without_invoking_models`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 88 | `—` | Verify that the model-free demo reports Laya, LLM and blocked outcomes in that order. |
## Account scenarios — 12 additional cases

Source: [test_account_scenarios.py](../tests/test_account_scenarios.py).
These use disposable app state. Eight PL-07 cases remain strict expected failures
based on their prior execution. AUTH-07 now passes with the implemented popup.
The initial focused run passed AUTH-07/AUTH-08 and exposed HOME-01;
the consolidated social run rechecks all four against the account/version guard. See [results and run instructions](adversarial-scenarios.md).

### `test_playlist_duplicate_names`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 89 | `exact-create` | Reject creation of a second same-account playlist named `Road trip`. |
| 90 | `exact-rename` | Reject renaming another playlist to the existing `Road trip` name. |
| 91 | `exact-concurrent_create` | Two concurrent creates using a previously unused name produce one success and one conflict. |
| 92 | `exact-concurrent_rename` | Two concurrent renames to a previously unused name produce one success and one conflict. |
| 93 | `trimmed-create` | Reject creation using the existing name padded with surrounding spaces. |
| 94 | `trimmed-rename` | Reject renaming to the existing name padded with surrounding spaces. |
| 95 | `trimmed-concurrent_create` | Concurrent creates using a whitespace-padded name produce one success and one conflict. |
| 96 | `trimmed-concurrent_rename` | Concurrent renames using a whitespace-padded name produce one success and one conflict. |

Every case also checks that another account may use the same name, self-rename
succeeds after trimming, and the original playlist and track membership remain intact.

### `test_auth_popup_repeated_activation_and_late_failure`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 97 | `—` | During synthetic album audio playback, authentication should open a dialog. Then repeat activation/dismissal, reopen with a login request pending, and release a late failure; verify no stale UI overwrite, navigation, duplicate dialogs or playback restart. |

Case 97 now passes through the popup interactions, rather than stopping at its old
navigation prerequisite failure.

### `test_auth_popup_mode_switching_clears_password_without_submitting`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 98 | `desktop` | Repeated login/register switching clears passwords, sends no auth requests, keeps background controls out of keyboard focus, and preserves playback; Close/reopen/Escape clear passwords and restore focus. Passed. |
| 99 | `mobile` | The same adversarial sequence at a 390×844 viewport. Passed. |

### `test_home_playlist_late_refresh_after_logout_does_not_restore_private_state`

| # | Parameter | Scenario and expected outcome |
| --- | --- | --- |
| 100 | `—` | Delay a private collection response until after landing-page logout; stale data must not repopulate client state or the signed-out UI. Regression for the original stale-state failure; the current account/version guard discards the old response. |

The original failing run is retained under `/tmp/radioworkx-adversarial-popup/`.
The current consolidated verification uses `/tmp/radioworkx-social/report.xml`.

## Social scenarios — 54 additional cases

Source files: [API tests](../tests/test_social_adversarial.py) and
[browser tests](../tests/test_social_browser.py). All cases use disposable QA data;
[scenario definitions and run instructions](adversarial-scenarios.md#social-feature-adversarial-scenarios)
explain the invariants and limitations. Each row gives the exact file-relative
pytest identifier, including parameterization.

| # | Scenario | Source | Test identifier |
| --- | --- | --- | --- |
| 101 | SOC-01 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc01_follow_races_with_revocation[unshare]` |
| 102 | SOC-01 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc01_follow_races_with_revocation[delete]` |
| 103 | SOC-02 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc02_republish_does_not_resubscribe_or_remove_listener_follow` |
| 104 | SOC-03 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc03_concurrent_last_slot_and_idempotency_at_limit[people]` |
| 105 | SOC-03 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc03_concurrent_last_slot_and_idempotency_at_limit[playlists]` |
| 106 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[rename-follower]` |
| 107 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[rename-guest]` |
| 108 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[add_track-follower]` |
| 109 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[add_track-guest]` |
| 110 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[remove_track-follower]` |
| 111 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[remove_track-guest]` |
| 112 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[delete-follower]` |
| 113 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[delete-guest]` |
| 114 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[share-follower]` |
| 115 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[share-guest]` |
| 116 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[unshare-follower]` |
| 117 | SOC-06 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc06_following_never_grants_owner_mutations[unshare-guest]` |
| 118 | SOC-07 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc07_disappearing_follow_does_not_fail_collection[unshare]` |
| 119 | SOC-07 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc07_disappearing_follow_does_not_fail_collection[delete]` |
| 120 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[profile-missing_header]` |
| 121 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[profile-foreign_origin]` |
| 122 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[profile-revoked]` |
| 123 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[share-missing_header]` |
| 124 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[share-foreign_origin]` |
| 125 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[share-revoked]` |
| 126 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[unshare-missing_header]` |
| 127 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[unshare-foreign_origin]` |
| 128 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[unshare-revoked]` |
| 129 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[follow_person-missing_header]` |
| 130 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[follow_person-foreign_origin]` |
| 131 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[follow_person-revoked]` |
| 132 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[unfollow_person-missing_header]` |
| 133 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[unfollow_person-foreign_origin]` |
| 134 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[unfollow_person-revoked]` |
| 135 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[follow_playlist-missing_header]` |
| 136 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[follow_playlist-foreign_origin]` |
| 137 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[follow_playlist-revoked]` |
| 138 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[unfollow_playlist-missing_header]` |
| 139 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[unfollow_playlist-foreign_origin]` |
| 140 | SOC-11 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc11_all_social_mutations_enforce_request_and_session_rules[unfollow_playlist-revoked]` |
| 141 | SOC-08 | [test_social_adversarial.py](../tests/test_social_adversarial.py) | `test_soc08_public_payloads_exclude_private_canaries` |
| 142 | SOC-05 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc05_old_responses_cannot_restore_account_or_refresh_state[logout-music]` |
| 143 | SOC-05 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc05_old_responses_cannot_restore_account_or_refresh_state[logout-social]` |
| 144 | SOC-05 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc05_old_responses_cannot_restore_account_or_refresh_state[account_switch-music]` |
| 145 | SOC-05 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc05_old_responses_cannot_restore_account_or_refresh_state[account_switch-social]` |
| 146 | SOC-05 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc05_old_responses_cannot_restore_account_or_refresh_state[newer_refresh-music]` |
| 147 | SOC-05 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc05_old_responses_cannot_restore_account_or_refresh_state[newer_refresh-social]` |
| 148 | SOC-04 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc04_duplicate_follow_and_old_button_after_rerender[people]` |
| 149 | SOC-04 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc04_duplicate_follow_and_old_button_after_rerender[playlists]` |
| 150 | SOC-09 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc09_cancel_then_authenticate_follow_during_playback` |
| 151 | SOC-08 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc08_names_render_as_text_in_public_and_follower_views` |
| 152 | SOC-10 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc10_clipboard_denial_single_fallback_and_revocation` |
| 153 | SOC-12 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc12_revoked_shared_page_rejects_follow_and_fresh_reads[unshare]` |
| 154 | SOC-12 | [test_social_browser.py](../tests/test_social_browser.py) | `test_soc12_revoked_shared_page_rejects_follow_and_fresh_reads[delete]` |

The consolidated run also includes the three existing social tests and four existing
account tests as regression checks. Those seven are not new adversarial cases and
are not included in the 154-case inventory above.

Consolidated verification: **153 passed, 8 expected failures** across the 154 listed
cases and seven existing regressions. All 54 social cases passed; expected failures
are exclusively PL-07. Report: `/tmp/radioworkx-social/report.html` (JUnit alongside).


## Agent framework verification (2026-09-29)

The original inventory above remains the scenario/router baseline. Additional harness
checks live in `tests/adversary/test_runtime.py` (29 cases) and
`tests/adversary/test_framework_browser.py` (two opt-in integration cases): origin
and redirect policy, credential selection, strict model output, atomic concurrent
call budgets, Browser Use dispatch accounting, durable/escaped artifacts, stable
fingerprints, corrupt/interrupted replay rejection, long-label candidates, two
isolated sessions and fresh-fixture replay. These are infrastructure tests, not
additional application attack scenarios. The framework suite totals 119 cases,
including the original 88. See [framework commands and limits](adversary-framework.md).
