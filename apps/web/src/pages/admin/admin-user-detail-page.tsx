import { AdminUsersPage } from "./admin-users-page";
import { useLastRouteParam } from "../use-last-route-param";

export function AdminUserDetailPage() {
  const userId = useLastRouteParam("userId") ?? "";
  return <AdminUsersPage selectedUserId={userId} />;
}
