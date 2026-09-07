"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { ReceiveGoodsForm } from "@/components/store-inventory/ReceiveGoodsForm";
import type { GoodsReceiptCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useFarm, useRecordGoodsReceipt } from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** STORE-INV-002A.2: thin client over `.1`'s already-shipped
 * `record_goods_receipt` command -- no new backend behavior here. */
export default function ReceiveGoodsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const mutation = useRecordGoodsReceipt(farmId);
  const [error, setError] = useState<AppError | null>(null);
  const [success, setSuccess] = useState<{ code: string } | null>(null);

  return (
    <div>
      <PageHeader
        title="Receive Goods"
        description={farm ? `Recording a receipt for ${farm.name}` : undefined}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Store & Inventory", href: `/farms/${farmId}/store-inventory` },
              { label: "Receive Goods" },
            ]}
          />
        }
      />

      {success ? (
        <div className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <h2 className="font-serif text-base font-semibold text-wl-text">Receipt recorded</h2>
          <p className="text-sm text-wl-text">
            Code <span className="font-medium">{success.code}</span>
          </p>
          <Button type="button" variant="primary" className="self-start" onClick={() => setSuccess(null)}>
            Record another receipt
          </Button>
        </div>
      ) : (
        <ReceiveGoodsForm
          isSubmitting={mutation.isPending}
          serverError={error}
          onSubmit={(payload: GoodsReceiptCreate) => {
            setError(null);
            mutation.mutate(payload, {
              onSuccess: (receipt) => setSuccess({ code: receipt.code }),
              onError: (err) => setError(asAppError(err)),
            });
          }}
        />
      )}
    </div>
  );
}
