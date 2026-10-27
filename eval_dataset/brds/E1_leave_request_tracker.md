# BRD: Employee Leave Request Tracker

Business owner: HR Operations Lead

## Overview
HR tracks leave requests in a shared spreadsheet. Managers miss requests and balances are often wrong. We need a simple internal tool for submitting and approving leave.

## Business Objectives
- Replace the leave spreadsheet for all 600 employees.
- Cut leave approval time to under 2 working days.

## Scope
### In Scope
- Web tool for employees, managers and HR.
### Out of Scope
- Payroll calculation.

## Functional Requirements
- FR-01 [Must] Employees submit leave requests with type, start date, end date and comment.
- FR-02 [Must] Managers approve or reject requests and the employee is notified by email.
- FR-03 [Must] Leave balances are calculated per employee and leave type.
- FR-04 [Should] HR exports a monthly leave report as CSV.
- FR-05 [Could] Team calendar view of approved leave.

## Non-Functional Requirements
- NFR-01 [Must] Employees sign in with corporate SSO.
- NFR-02 [Should] 99.5% availability during business hours.

## Integrations
- INT-01 HRIS employee directory API for employee and manager data.

## Constraints
- Go-live within 8 weeks.
- Team of 3 engineers.

## Success Metrics
- 90% of leave requests submitted through the tool within one month.
