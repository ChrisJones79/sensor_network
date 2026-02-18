from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_db
from ..models import DashboardPlotConfig
from ..schemas import DashboardPlotConfigPayload, PlotConfig

router = APIRouter(prefix="/api", tags=["plots"])



def _default_payload() -> DashboardPlotConfigPayload:
    return DashboardPlotConfigPayload(
        plots=[
            PlotConfig(
                plot_id="plot-1",
                title="Plot 1",
                y_axis_label="",
                live_mode=True,
                traces=[],
                options={},
            )
        ]
    )


@router.get("/plots/config", response_model=DashboardPlotConfigPayload)
def get_plot_config(db: Session = Depends(get_db)) -> DashboardPlotConfigPayload:
    row = db.scalars(select(DashboardPlotConfig).where(DashboardPlotConfig.scope == "global")).first()
    if row is None:
        return _default_payload()
    return DashboardPlotConfigPayload.model_validate(row.config_json)


@router.post("/plots/config", response_model=DashboardPlotConfigPayload)
def set_plot_config(payload: DashboardPlotConfigPayload, db: Session = Depends(get_db)) -> DashboardPlotConfigPayload:
    row = db.scalars(select(DashboardPlotConfig).where(DashboardPlotConfig.scope == "global")).first()
    if row is None:
        row = DashboardPlotConfig(scope="global", config_json=payload.model_dump(mode="json"))
        db.add(row)
    else:
        row.config_json = payload.model_dump(mode="json")

    db.commit()
    return payload
