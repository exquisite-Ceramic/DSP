using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Core.Execution;
using Xunit;

namespace Revit.AgentHost.Core.Tests;

public sealed class WallThicknessPlannerTests
{
    [Fact]
    public void One_editable_layer_without_fixed_layers_takes_requested_total()
    {
        WallThicknessPlan plan = WallThicknessPlanner.Plan(
            requestedTotalInternal: 12.0,
            layers: new[] { Layer(0, 5.0, canSetWidth: true) },
            tolerance: 0.001);

        Assert.Equal(0, plan.EditableLayerIndex);
        Assert.Equal(12.0, plan.RequestedTotalInternal);
        Assert.Equal(12.0, plan.NewEditableLayerWidthInternal);
    }

    [Fact]
    public void Fixed_layers_are_subtracted_from_requested_total()
    {
        WallThicknessPlan plan = WallThicknessPlanner.Plan(
            requestedTotalInternal: 12.0,
            layers: new[]
            {
                Layer(0, 2.0, canSetWidth: false),
                Layer(1, 5.0, canSetWidth: true),
                Layer(2, 3.0, canSetWidth: false),
            },
            tolerance: 0.001);

        Assert.Equal(1, plan.EditableLayerIndex);
        Assert.Equal(7.0, plan.NewEditableLayerWidthInternal);
    }

    [Fact]
    public void Zero_editable_layers_is_ambiguous()
    {
        WallThicknessPlanningException error = Assert.Throws<WallThicknessPlanningException>(
            () => WallThicknessPlanner.Plan(
                10.0,
                new[]
                {
                    Layer(0, 4.0, canSetWidth: false),
                    Layer(1, 0.0, canSetWidth: true, isMembrane: true),
                },
                0.001));

        Assert.Equal("AMBIGUOUS_WALL_THICKNESS_LAYER", error.Code);
    }

    [Fact]
    public void Two_editable_layers_is_ambiguous()
    {
        WallThicknessPlanningException error = Assert.Throws<WallThicknessPlanningException>(
            () => WallThicknessPlanner.Plan(
                10.0,
                new[]
                {
                    Layer(0, 4.0, canSetWidth: true),
                    Layer(1, 6.0, canSetWidth: true),
                },
                0.001));

        Assert.Equal("AMBIGUOUS_WALL_THICKNESS_LAYER", error.Code);
    }

    [Fact]
    public void Membrane_layer_is_never_selected_as_editable()
    {
        WallThicknessPlan plan = WallThicknessPlanner.Plan(
            10.0,
            new[]
            {
                Layer(0, 0.0, canSetWidth: true, isMembrane: true),
                Layer(1, 5.0, canSetWidth: true),
            },
            0.001);

        Assert.Equal(1, plan.EditableLayerIndex);
    }

    [Fact]
    public void Requested_total_not_greater_than_fixed_sum_is_invalid()
    {
        WallThicknessPlanningException error = Assert.Throws<WallThicknessPlanningException>(
            () => WallThicknessPlanner.Plan(
                5.0,
                new[]
                {
                    Layer(0, 2.0, canSetWidth: false),
                    Layer(1, 1.0, canSetWidth: true),
                    Layer(2, 3.0, canSetWidth: false),
                },
                0.001));

        Assert.Equal("INVALID_WALL_THICKNESS", error.Code);
    }

    [Theory]
    [InlineData(0.0)]
    [InlineData(-1.0)]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    public void Non_positive_or_non_finite_requested_total_is_invalid(double requested)
    {
        WallThicknessPlanningException error = Assert.Throws<WallThicknessPlanningException>(
            () => WallThicknessPlanner.Plan(
                requested,
                new[] { Layer(0, 1.0, canSetWidth: true) },
                0.001));

        Assert.Equal("INVALID_WALL_THICKNESS", error.Code);
    }

    [Fact]
    public void Non_finite_fixed_width_cannot_produce_a_plan()
    {
        WallThicknessPlanningException error = Assert.Throws<WallThicknessPlanningException>(
            () => WallThicknessPlanner.Plan(
                10.0,
                new[]
                {
                    Layer(0, double.NaN, canSetWidth: false),
                    Layer(1, 1.0, canSetWidth: true),
                },
                0.001));

        Assert.Equal("INVALID_WALL_THICKNESS", error.Code);
    }

    [Fact]
    public void Reconstructed_total_matches_requested_total_within_supplied_tolerance()
    {
        const double tolerance = 0.001;
        WallLayerSnapshot[] layers =
        {
            Layer(0, 2.0, canSetWidth: false),
            Layer(1, 4.0, canSetWidth: true),
            Layer(2, 3.0, canSetWidth: false),
        };

        WallThicknessPlan plan = WallThicknessPlanner.Plan(13.0, layers, tolerance);
        double fixedSum = layers.Where(layer => layer.LayerIndex != plan.EditableLayerIndex)
            .Sum(layer => layer.WidthInternal);
        double reconstructed = fixedSum + plan.NewEditableLayerWidthInternal;

        Assert.InRange(Math.Abs(reconstructed - plan.RequestedTotalInternal), 0.0, tolerance);
        Assert.True(double.IsFinite(plan.NewEditableLayerWidthInternal));
        Assert.True(plan.NewEditableLayerWidthInternal > 0.0);
    }

    private static WallLayerSnapshot Layer(
        int index,
        double width,
        bool canSetWidth,
        bool isMembrane = false)
    {
        return new WallLayerSnapshot(index, width, isMembrane, canSetWidth);
    }
}
