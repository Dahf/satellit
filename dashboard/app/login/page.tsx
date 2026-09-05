import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  return (
    <div className="mx-auto max-w-sm pt-16">
      <Card>
        <CardHeader>
          <CardTitle>Satellit</CardTitle>
          <CardDescription>Passwort aus DASHBOARD_PASSWORD.</CardDescription>
        </CardHeader>
        <CardContent>
          <form action="/api/login" method="post" className="space-y-3">
            <input type="hidden" name="next" value={sp.next ?? "/"} />
            <div className="space-y-1">
              <Label htmlFor="password">Passwort</Label>
              <Input id="password" name="password" type="password" autoFocus required />
            </div>
            {sp.error ? <p className="text-sm text-red-600">Falsches Passwort.</p> : null}
            <Button type="submit" className="w-full">Anmelden</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
