# **DOWF** [*Dowf Outlines Work Flow*]

DOWF converts structured project plans stored in Excel into machine-readable YAML, dependency diagrams, and timeline visualisations. It was developed for large collaborative research projects such as research grants, but can be used for any programme involving work packages, deliverables, milestones, ownership, risks, and dependencies.

DOWF is a lightweight Python toolkit for research grants and collaborative projects.

The system converts a structured Excel workbook into:
- YAML project definitions
- Work package dependency maps
- Deliverable and milestone diagrams
- Gantt charts


## Input Structure

### Overview.xlsx

Workbook containing:

### Sheet: WPs

| WP | Title | Lead |
|----|--------|--------|
| WP1 | Project Management | LPD |
| WP2 | Doing stuff | LLC |

### Sheet: Tasks

| WP | ID | Title | Lead | Status | Progress | Start | Due | Notes | Risks |
|----|----|-------|------|--------|----------|-------|-----|--------|--------|
| WP2 | D2.1 | The best stuff | LLC | Done | 100 | 01/02/1999 | 31/03/1999 |  |  |
| WP2 | D2.3 | Dowf stuff | LPD | Delayed | 10 | 01/04/1999 | 30/04/1999 | Problems! | Weather |
| WP2 | D2.6a | Bits of stuff | LLC | Started | 35 | 01/06/1999 | 31/10/1999 |  |  |
| WP2 | M2 | The stuff report | LLC | Not Started | 0 | 01/08/1999 | 31/12/1999 |  | Management |

### Sheet: Dependencies

| From | To |
|--------|--------|
| D2.1 | M2 |
| D2.3 | D2.6a |


### Sheet: Partners

| Partner | NodeColour | ClusterColour | Contact | Email | Phone | Address |
|------|--------|----------|-------|-----|--------|--------|
| LPD | #502DE3 | #BEB1F5 |  |  |  |  |
| LLC | #2FBF92 | #A0E8D2 |  |  |  |  |

### Sheet: Statuses

| Status | BorderColour | Action |
|------|--------|----------|
| Ongoing | #DC2626 | |



### Sheet: Risks

Risk registor not done yet

# Testing

Run:
`python excel_to_yaml.py Example.xlsx Example_Overview.yaml Example_Colours.yaml`
`python GANTT_yaml.py Example_Overview.yaml out.svg --colours Example_Colours.yaml`
`python FlowDiagram_yaml.py Example_Overview.yaml out.svg --colours Example_Colours.yaml`

and to just focus on one patner
`python FlowDiagram_yaml.py Example_Overview.yaml out.svg --colours Example_Colours.yaml LLC`

### Defaults

if the excel is called `Overview.xlsx` then you can just run.
`python excel_to_yaml.py`
`python GANTT_yaml.py`
`python FlowDiagram_yaml.py`

and to just focus on one patner
`python FlowDiagram_yaml.py LLC`

## Workflow

Overview.xlsx

↓

Overview.yaml

↓

Project Diagram.svg and/or Gantt Chart.svg


## Motivation

Many research projects maintain separate spreadsheets, Gantt charts, during writing, these all have to be updated to keep consistency. 
Dowf aims to establish a single source from which all project planning outputs can be generated automatically.


## Future Development
- Dependency editor
- Risk register
- HTML output with links
