import { useCallback, useEffect, useState } from "react";

import type { SleipnirBridge } from "../bridge";
import type { DashboardSnapshot } from "../domain/types";

export function useSleipnir(bridge: SleipnirBridge) {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSnapshot(await bridge.loadDashboard());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not connect to Sleipnir");
    }
  }, [bridge]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runAndRefresh = useCallback(
    async <T,>(operation: () => Promise<T>) => {
      const result = await operation();
      await refresh();
      return result;
    },
    [refresh],
  );

  return { snapshot, error, refresh, runAndRefresh };
}
